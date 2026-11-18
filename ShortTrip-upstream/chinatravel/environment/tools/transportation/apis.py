import os
import json
import heapq
import math
import statistics
from hashlib import sha256
from pathlib import Path
from geopy.distance import geodesic
from geographiclib.geodesic import Geodesic

from chinatravel.environment.tools.poi.apis import Poi
from chinatravel.environment.language import CITY_SLUGS, city_names, normalize_lang, relative_database_path


def _city_poi_reference(city, subway_path):
    """Use the local same-city POI median only as a coarse sanity boundary."""
    path=Path(subway_path).resolve().parent.parent/'poi'/city/'poi.json'
    if not path.is_file():return None
    raw=path.read_bytes()
    rows=json.loads(raw.decode('utf-8-sig'))
    positions=[]
    for row in rows:
        p=row.get('position') if isinstance(row,dict) else None
        if not isinstance(p,(list,tuple)) or len(p)!=2:continue
        try:lat,lon=map(float,p)
        except (TypeError,ValueError):continue
        if math.isfinite(lat) and math.isfinite(lon) and 15<=lat<=55 and 70<=lon<=140:
            positions.append((lat,lon))
    if len(positions)<10:return None
    return {'latitude':statistics.median(p[0] for p in positions),
            'longitude':statistics.median(p[1] for p in positions),
            'count':len(positions),'source_sha256':sha256(raw).hexdigest(),
            'method':'same-city POI median; coarse +/-2 latitude and +/-3 longitude degrees'}


def _normalize_station_position(raw_position, reference):
    """Return unique China/city-consistent ordering, or preserve unknown."""
    result={'raw_position':raw_position,'state':'unknown','coordinate_order':None,
            'normalized_position':None,'reference':reference}
    if not isinstance(raw_position,str) or reference is None:
        result['reason']='missing_raw_coordinate_or_city_reference';return result
    try:
        a,b=map(float,raw_position.split(','))
    except (ValueError,TypeError):
        result['reason']='invalid_coordinate';return result
    if not math.isfinite(a) or not math.isfinite(b):
        result['reason']='nonfinite_coordinate';return result
    candidates=[]
    for order,lat,lon in [('latitude_longitude',a,b),('longitude_latitude',b,a)]:
        if (15<=lat<=55 and 70<=lon<=140
                and abs(lat-reference['latitude'])<=2 and abs(lon-reference['longitude'])<=3):
            candidates.append((order,lat,lon))
    if len(candidates)!=1:
        result['reason']='city_coordinate_order_ambiguous_or_out_of_range';return result
    order,lat,lon=candidates[0]
    result.update(state='accepted',coordinate_order=order,normalized_position=[lat,lon],
                  reason='unique_china_and_same_city_poi_bounds')
    return result


def get_lines_and_stations(city, SUBWAY_PATH, evidence_out=None):
    stations_all = []
    metro_lines = {}
    raw=Path(SUBWAY_PATH).read_bytes()
    subway_data=json.loads(raw.decode('utf-8-sig'))
    reference=_city_poi_reference(city,SUBWAY_PATH)
    source_sha=sha256(raw).hexdigest()
    for line in subway_data[city]:
        metro_lines[line["name"]] = []
        for station in line["stations"]:
            evidence=_normalize_station_position(station.get('position'),reference)
            evidence.update(city=city,line=line['name'],name=station.get('name'),source_sha256=source_sha)
            if evidence_out is not None:evidence_out.append(evidence)
            metro_lines[line["name"]].append(station["name"])
            if evidence['state']=='accepted':
                stations_all.append({"name": station["name"], "position": tuple(evidence['normalized_position'])})
    station_to_line = {}
    for line, stations in metro_lines.items():
        for station in stations:
            station_to_line[station] = line
    return stations_all, metro_lines, station_to_line


def build_graph(metro_lines):
    graph = {}
    for line, stations in metro_lines.items():
        for i in range(len(stations)):
            if stations[i] not in graph:
                graph[stations[i]] = []
            if i > 0:
                graph[stations[i]].append(stations[i - 1])
            if i < len(stations) - 1:
                graph[stations[i]].append(stations[i + 1])
    return graph


def get_line_change(station_to_line, path):
    line_changes = []

    for station in path:
        if station in station_to_line:
            line_changes.append(station_to_line[station])


def add_time(time1, hours):

    hour, minu = int(time1.split(":")[0]), int(time1.split(":")[1])

    time_delta = int(hours * 60)
    min_new = minu + time_delta

    if min_new >= 60:
        hour_new = hour + int(min_new / 60)
        min_new = min_new % 60
    else:
        hour_new = hour

    if hour_new < 10:
        time_new = "0" + str(hour_new) + ":"
    else:
        time_new = str(hour_new) + ":"
    if min_new < 10:

        time_new = time_new + "0" + str(min_new)
    else:
        time_new = time_new + str(min_new)

    return time_new


def dijkstra(graph, start, end):
    queue = [(0, start, [])]
    seen = set()
    while queue:
        (cost, node, path) = heapq.heappop(queue)
        if node in seen:
            continue
        path = path + [node]
        seen.add(node)
        if node == end:
            return path
        for next_node in graph.get(node, []):
            if next_node not in seen:
                heapq.heappush(queue, (cost + 1, next_node, path))
    return []


def find_shortest_path(graph, start, end):
    return dijkstra(graph, start, end)


def find_nearest_station(location, stations):
    nearest_station = None
    min_distance = float("inf")
    latitude, longitude = location
    inverse = Geodesic.WGS84.Inverse
    for station in stations:
        station_latitude, station_longitude = station["position"]
        distance = (
            inverse(
                latitude,
                longitude,
                station_latitude,
                station_longitude,
            )["s12"]
            / 1000.0
        )
        if distance < min_distance:
            min_distance = distance
            nearest_station = station
    return nearest_station, min_distance


def calculate_cost_taxi(distance):
    if distance <= 1.8:
        return 11.0
    elif distance <= 10:
        return 11.0 + (distance - 1.8) * 3.5
    else:
        return 11.0 + (10 - 1.8) * 3.5 + (distance - 10) * 4.5


def calculate_cost(distance):
    if distance <= 4:
        return 2
    elif distance <= 9:
        return 3
    elif distance <= 14:
        return 4
    elif distance <= 21:
        return 5
    elif distance <= 28:
        return 6
    elif distance <= 37:
        return 7
    elif distance <= 48:
        return 8
    elif distance <= 61:
        return 9
    else:
        extra_distance = distance - 61
        extra_cost = (extra_distance + 14) // 15
        return 9 + extra_cost


class Transportation:
    def __init__(
        self, base_path: str = None, en_version=False, lang=None
    ):
        self.lang = normalize_lang(lang, en_version=en_version)
        if base_path is None:
            base_path = relative_database_path(self.lang, "transportation")
        self.city_list = CITY_SLUGS
        self.city_list_chinese = city_names(self.lang)

        curdir = os.path.dirname(os.path.realpath(__file__))
        SUBWAY_PATH = os.path.join(curdir, base_path, "subways.json")
        self.city_stations_dict = {}
        self.city_lines_dict = {}
        self.city_station_to_line = {}
        self.station_coordinate_evidence = {}
        for city in self.city_list:
            self.station_coordinate_evidence[city] = []
            stations_all, metro_lines, station_to_line = get_lines_and_stations(
                city, SUBWAY_PATH, self.station_coordinate_evidence[city]
            )
            self.city_stations_dict[city] = stations_all
            self.city_lines_dict[city] = metro_lines
            self.city_station_to_line[city] = station_to_line

        self.graphs = {}
        for city in self.city_list:
            self.graphs[city] = build_graph(self.city_lines_dict[city])

        self.poi_search = Poi(lang=self.lang)
        self._nearest_station_cache = {}

    def _find_nearest_station(self, city, location_name, location):
        cache_key = (city, location_name)
        if cache_key not in self._nearest_station_cache:
            self._nearest_station_cache[cache_key] = find_nearest_station(
                location,
                self.city_stations_dict[city],
            )
        return self._nearest_station_cache[cache_key]

    def goto(self, city, start, end, start_time, transport_type, verbose=False):
        if transport_type not in ["walk", "metro", "taxi"]:
            return "only support transport_type in ['walk','metro','taxi']"
        locationA = start
        locationB = end
        coordinate_A = self.poi_search.search(city, locationA)
        coordinate_B = self.poi_search.search(city, locationB)
        city_cn = city
        if city in self.city_list_chinese:
            city = self.city_list[self.city_list_chinese.index(city)]
        elif isinstance(city, str) and city.lower() in self.city_list:
            city = city.lower()
        locationA_name, locationB_name = locationA, locationB
        locationA, locationB = coordinate_A, coordinate_B
        transports = []
        if transport_type == "walk":
            distance = geodesic(locationA, locationB).kilometers
            walking_speed = 5.0
            time = distance / walking_speed
            cost = 0.0
            end_time = add_time(start_time, time)
            transport = {
                "start": locationA_name,
                "end": locationB_name,
                "mode": "walk",
                "start_time": start_time,
                "end_time": end_time,
                "cost": cost,
                "distance": distance,
            }
            transports.append(transport)
            if verbose:
                print(
                    "Walk Distance {:.3} kilometers, Time {:.3} hour, Cost {}¥".format(
                        distance, time, int(cost)
                    )
                )
            return transports

        elif transport_type == "taxi":
            distance = geodesic(locationA, locationB).kilometers
            taxi_speed = 40.0
            time = distance / taxi_speed
            cost = calculate_cost_taxi(distance)
            end_time = add_time(start_time, time)
            transport = {
                "start": locationA_name,
                "end": locationB_name,
                "mode": "taxi",
                "start_time": start_time,
                "end_time": end_time,
                "cost": round(cost, 2),
                "distance": round(distance, 2),
            }
            transports.append(transport)
            if verbose:
                print(
                    "Taxi Distance {:.3} kilometers, Time {:.2} hour, Cost {}¥".format(
                        distance, time, int(cost)
                    )
                )
            return transports

        elif transport_type == "metro":
            graph = self.graphs[city]
            stationA, distanceA = self._find_nearest_station(
                city,
                locationA_name,
                locationA,
            )
            stationB, distanceB = self._find_nearest_station(
                city,
                locationB_name,
                locationB,
            )
            if not stationA or not stationB:
                return "No solution: station coordinates unavailable"
            if stationA == stationB:
                if verbose:
                    print("Too near. Walk.")
                return "No solution"
                return self.goto(
                    city_cn,
                    locationA_name,
                    locationB_name,
                    start_time,
                    transport_type="walk",
                    verbose=verbose,
                )
            shortest_path = find_shortest_path(
                graph, stationA["name"], stationB["name"]
            )
            if not shortest_path:
                return "No solution: disconnected subway graph"
            if stationA and stationB:
                distance_between_stations = geodesic(
                    stationA["position"], stationB["position"]
                ).kilometers
                subway_speed = 30.0
                time_between_stations = distance_between_stations / subway_speed
                walking_speed = 5.0
                timeA = distanceA / walking_speed
                timeB = distanceB / walking_speed
                total_time = timeA + time_between_stations + timeB
                cost = calculate_cost(distance_between_stations)
                distance = distanceA + distance_between_stations + distanceB
                end_timeA = add_time(start_time, timeA)
                end_timeB = add_time(end_timeA, time_between_stations)
                end_time_final = add_time(end_timeB, timeB)
                end_time = end_time_final
                transports.append(
                    {
                        "start": locationA_name,
                        "end": self._station_name(stationA["name"]),
                        "mode": "walk",
                        "start_time": start_time,
                        "end_time": end_timeA,
                        "cost": 0,
                        "distance": round(distanceA, 2),
                    }
                )
                transports.append(
                    {
                        "start": self._station_name(stationA["name"]),
                        "end": self._station_name(stationB["name"]),
                        "mode": "metro",
                        "start_time": end_timeA,
                        "end_time": end_timeB,
                        "cost": cost,
                        "distance": round(distance_between_stations, 2),
                    }
                )
                transports.append(
                    {
                        "start": self._station_name(stationB["name"]),
                        "end": locationB_name,
                        "mode": "walk",
                        "start_time": end_timeB,
                        "end_time": end_time,
                        "cost": 0,
                        "distance": round(distanceB, 2),
                    }
                )
                if verbose:
                    print(
                        "Walk: From starting point to metro {}, Distance: {}.".format(
                            self._station_name(stationA["name"]), distanceA
                        )
                    )
                    print(
                        f"Subway: From {self._station_name(stationA['name'])} to {self._station_name(stationB['name'])}: {' -> '.join(shortest_path)}"
                    )
                    print("The cost of subway: {}¥".format(cost))
                    print(
                        "Walk: From metro {} to ending point,  Distance: {}.".format(
                            self._station_name(stationB["name"]), distanceB
                        )
                    )
                return transports
            else:
                raise NotImplementedError

    def _metro_station_suffix(self):
        return "-Metro Station" if self.lang == "en" else "-地铁站"

    def _station_name(self,name):
        suffix=self._metro_station_suffix()
        if name.endswith(suffix) or (self.lang!='en' and '地铁站' in name):return name
        return name+suffix
