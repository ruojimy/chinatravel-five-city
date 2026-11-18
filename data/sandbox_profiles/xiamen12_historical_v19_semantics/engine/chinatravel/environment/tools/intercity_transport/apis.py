import os
import pandas as pd
from pandas import DataFrame
from chinatravel.environment.airports import airport_matches, airport_display
from chinatravel.environment.language import CITY_NAMES, normalize_lang, relative_database_path


def time2float(time_str):
    h, m = time_str.split(":")
    return int(h) + int(m) / 60


class IntercityTransport:
    def reference_flights(self, start_city, end_city, travel_date=None):
        """Expose dated third-party offers as references, never as booked flights."""
        root = os.environ.get('CT_FLIGHT_REFERENCE_ROOT')
        if not root or not travel_date:
            return []
        import sys
        runtime = os.environ.get('CT_SANDBOX_RUNTIME_DIR')
        if runtime and runtime not in sys.path:
            sys.path.insert(0, runtime)
        from flight_reference import lookup
        return lookup(root, start_city, end_city, travel_date)

    def __init__(self, path: str = None, lang=None):
        self.lang = normalize_lang(lang)
        curdir = os.path.dirname(os.path.realpath(__file__))
        if path is None:
            path = relative_database_path(self.lang, "intercity_transport")
        self.base_path = os.path.join(curdir, path)
        self.airplane_path = os.path.join(self.base_path, "airplane.jsonl")
        self.airplane_df = pd.read_json(
            self.airplane_path, lines=True, keep_default_dates=False
        )
        city_list = CITY_NAMES["zh"]
        exposed_city_list = CITY_NAMES[self.lang]
        self.train_df_dict = {}

        for start_idx, start_city in enumerate(city_list):
            for end_idx, end_city in enumerate(city_list):
                if start_city == end_city:
                    continue
                train_path = (
                    os.path.join(
                        self.base_path,
                        "train",
                        "from_{}_to_{}.json".format(start_city, end_city),
                    )
                )
                train_df = pd.read_json(train_path)
                self.train_df_dict[
                    (exposed_city_list[start_idx], exposed_city_list[end_idx])
                ] = train_df

    def select(
        self, start_city, end_city, intercity_type, earliest_leave_time="00:00", *, travel_date=None, seat_code=None
    ) -> DataFrame:
        if intercity_type not in ["train", "airplane"]:
            return "only support intercity_type in ['train','airplane']"
        res = self._select(start_city, end_city, intercity_type, travel_date=travel_date, seat_code=seat_code)
        bool_list = [False] * len(res)
        earliest = time2float(earliest_leave_time)
        for i in range(len(res)):
            try:
                begin, end = res.loc[i, "BeginTime"], res.loc[i, "EndTime"]
                cost, duration = res.loc[i, "Cost"], res.loc[i, "Duration"]
                # A missing price becomes NaN rather than a fabricated zero;
                # planners that require a budget see only eligible rows.
                if pd.isna(cost) or pd.isna(duration) or duration <= 0:
                    continue
                begin_float, end_float = time2float(begin), time2float(end)
                if not (0 <= begin_float <= 24 and 0 <= end_float <= 24):
                    continue
                bool_list[i] = begin_float >= earliest
            except (AttributeError, TypeError, ValueError, KeyError):
                continue
        return res[bool_list]

    def _select(self, start_city, end_city, intercity_type, *, travel_date=None, seat_code=None) -> DataFrame:
        # intercity_type=='train' | 'airplane'
        if intercity_type == "airplane":

            if len(self.airplane_df) == 0:
                return self.airplane_df.copy()

            mask = self.airplane_df.apply(
                lambda row: airport_matches(row.get("From"), start_city, row.get("FromName"))
                and airport_matches(row.get("To"), end_city, row.get("ToName")), axis=1)
            filtered_flights = self.airplane_df[mask].copy()
            # Preserve the source code while providing the source-supplied airport
            # name to the planner, POI routing and official verifier consistently.
            for key in ("From", "To"):
                name_key = key + "Name"
                if name_key in filtered_flights:
                    original = filtered_flights[key].copy()
                    filtered_flights[key + "Original"] = original
                    filtered_flights[key] = [airport_display(v, n) for v, n in
                                             zip(original, filtered_flights[name_key])]

            for key in ("Cost", "Duration"):
                if key in filtered_flights:
                    numeric = pd.to_numeric(filtered_flights[key], errors="coerce")
                    filtered_flights[key] = numeric.where(numeric >= 0)
            sorted_flights = filtered_flights.sort_values(by="BeginTime").reset_index(
                drop=True
            )
            return sorted_flights
        if intercity_type == "train":

            filtered_trains = self.train_df_dict[(start_city, end_city)].copy()
            use_historical = (os.environ.get("CT_XIAMEN_HISTORICAL_FARES") == "1"
                              and not travel_date and not seat_code)
            if not use_historical and "BenchmarkHistoricalScheduleOnly" in filtered_trains:
                historical_rows = filtered_trains["BenchmarkHistoricalScheduleOnly"].eq(True)
                filtered_trains = filtered_trains.loc[~historical_rows].copy()
            for key in ("Cost", "Duration"):
                if key in filtered_trains:
                    numeric = pd.to_numeric(filtered_trains[key], errors="coerce")
                    filtered_trains[key] = numeric.where(numeric >= 0)
            # Frozen benchmark opt-in: retain dates and uncertainty, never use for a dated query.
            if use_historical and "BenchmarkHistoricalCost" in filtered_trains:
                values = pd.to_numeric(filtered_trains["BenchmarkHistoricalCost"], errors="coerce")
                eligible = filtered_trains["Cost"].isna() & values.notna() & (values >= 0)
                filtered_trains.loc[eligible, "Cost"] = values.loc[eligible]
                filtered_trains.loc[eligible, "CostSource"] = "12306_historical_benchmark_reference"
                filtered_trains.loc[eligible, "CostDate"] = filtered_trains.loc[eligible, "BenchmarkFareDate"]
                filtered_trains.loc[eligible, "CostSeatCode"] = filtered_trains.loc[eligible, "BenchmarkFareSeat"]
                filtered_trains.loc[eligible, "CostAvailability"] = "unknown"
                filtered_trains.loc[eligible, "CostActualPurchasePrice"] = "unknown"
            if travel_date and seat_code:
                from chinatravel.environment.official_fare_runtime import apply
                filtered_trains = apply(filtered_trains, travel_date=travel_date, seat_code=seat_code,
                                        origin_city=start_city, destination_city=end_city, add_new=True)
            if filtered_trains.empty:
                return filtered_trains
            return filtered_trains.sort_values(by="BeginTime").reset_index(drop=True)


if __name__ == "__main__":
    a = IntercityTransport()
    city_list = [
        "上海",
        "北京",
        "深圳",
        "广州",
        "重庆",
        "苏州",
        "成都",
        "杭州",
        "武汉",
        "南京",
    ]
    city_en_list = [
        "shanghai",
        "beijing",
        "shenzhen",
        "guangzhou",
        "chongqing",
        "suzhou",
        "chengdu",
        "hangzhou",
        "wuhan",
        "nanjing",
    ]
    str_list = []
    for i in range(len(city_list)):
        for j in range(i + 1, len(city_list)):
            tmp_len = 0

            tmp = a.select(city_list[i], city_list[j], "train")
            if not isinstance(tmp, DataFrame):
                tmp_len = 0
            else:
                tmp_len = len(tmp)
            if tmp_len > 0:
                str_list.append(
                    "('{}','{}','{}',{})".format(
                        city_en_list[i], city_en_list[j], "train", tmp_len
                    )
                )

            tmp = a.select(city_list[j], city_list[i], "train")
            if not isinstance(tmp, DataFrame):
                tmp_len = 0
            else:
                tmp_len = len(tmp)
            if tmp_len > 0:
                str_list.append(
                    "('{}','{}','{}',{})".format(
                        city_en_list[j], city_en_list[i], "train", tmp_len
                    )
                )

            tmp = a.select(city_list[i], city_list[j], "flight")
            if not isinstance(tmp, DataFrame):
                tmp_len = 0
            else:
                tmp_len = len(tmp)
            if tmp_len > 0:
                str_list.append(
                    "('{}','{}','{}',{})".format(
                        city_en_list[i], city_en_list[j], "airplane", tmp_len
                    )
                )

            tmp = a.select(city_list[j], city_list[i], "flight")
            if not isinstance(tmp, DataFrame):
                tmp_len = 0
            else:
                tmp_len = len(tmp)
            if tmp_len > 0:
                str_list.append(
                    "('{}','{}','{}',{})".format(
                        city_en_list[j], city_en_list[i], "airplane", tmp_len
                    )
                )

    print(",\n".join(str_list))
