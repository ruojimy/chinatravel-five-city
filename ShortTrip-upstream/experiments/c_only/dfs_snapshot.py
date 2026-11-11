"""Original DFS snapshot with explicit B/C meal/date/wait hooks; see dfs_changes.diff."""
from chinatravel.agent.nesy_agent.nesy_agent import *
def dfs_poi(
    self, query, poi_plan, plan, current_time, current_position, current_day=0
):

    self.search_nodes += 1
    if (
        time.time() - self.time_before_search
        > self.TIME_CUT + self.llm_inference_time_count
    ):

        raise TimeOutError

    if self.check_if_too_late(
        query, current_day, current_time, current_position, poi_plan
    ):
        self.backtrack_count += 1
        print("The current time is too late to go hotel or back-transport, backtrack...")
        return False, plan

    # Prefix budget lower bounds are checked by ExperimentAgent.dfs_poi.

    # intercity_transport - go
    if current_day == 0 and current_time == "":
        plan = [{"day": current_day + 1, "activities": []}]
        plan[current_day]["activities"] = self.add_intercity_transport(
            plan[current_day]["activities"],
            poi_plan["go_transport"],
            innercity_transports=[],
            tickets=self.query["people_number"],
        )
        current_day, new_time = self.outbound_next(poi_plan["go_transport"])
        new_position = poi_plan["go_transport"]["To"]
        success, plan = self.dfs_poi(
            query, poi_plan, plan, new_time, new_position, current_day
        )
        if success:
            return True, plan
        else:
            self.backtrack_count += 1
            print("No solution for the given Go Transport, backtrack...")
            return False, plan

    # breakfast
    if False:  # Experimental breakfast is a searchable meal, not unconditional.

        if len(plan) < current_day + 1:
            plan.append({"day": current_day + 1, "activities": []})

        self.search_nodes += 1
        plan = self.select_and_add_breakfast(
            plan, poi_plan, current_day, current_time, current_position
        )

        new_time = plan[current_day]["activities"][-1]["end_time"]
        new_position = current_position
        success, plan = self.dfs_poi(
            query, poi_plan, plan, new_time, new_position, current_day
        )
        if success:
            return True, plan

        plan[current_day]["activities"].pop()

        candidates_type = []
        if current_day == query["days"] - 1 and current_time != "":
            candidates_type.append("back-intercity-transport")
        else:

            self.backtrack_count += 1
            print("No solution for the given Breakfast, backtrack...")

            return False, plan

    else:
        haved_lunch_today, haved_dinner_today = False, False

        for act_i in plan[current_day]["activities"]:
            if act_i["type"] == "lunch":
                haved_lunch_today = True
            if act_i["type"] == "dinner":
                haved_dinner_today = True

        candidates_type = ["attraction"]
        if not any(a["type"] == "breakfast" for a in plan[current_day]["activities"]):
            candidates_type.append("breakfast")
        if not haved_lunch_today:
            candidates_type.append("lunch")
        if not haved_dinner_today:
            candidates_type.append("dinner")
        if ("accommodation" in poi_plan) and (current_day < query["days"] - 1):
            candidates_type.append("hotel")
        if current_day == query["days"] - 1 and current_time != "":
            candidates_type.append("back-intercity-transport")

    print("candidates_type: ", candidates_type)

    while len(candidates_type) > 0:

        poi_type, candidates_type = self.select_next_poi_type(
            candidates_type,
            plan,
            poi_plan,
            current_day,
            current_time,
            current_position,
        )

        if not candidates_type:
            return False, plan

        print(
            "POI planning, day {} {}, {}, next-poi type: {}".format(
                current_day, current_time, current_position, poi_type
            )
        )

        if poi_type == "back-intercity-transport":

            if len(plan) < current_day + 1:
                plan.append({"day": current_day + 1, "activities": []})

            # transports_ranking = self.ranking_innercity_transport(current_position, poi_plan["back_transport"]["From"], current_day, current_time)
            transports_ranking = self.innercity_transports_ranking_from_query
            for trans_type_sel in transports_ranking:
                self.search_nodes += 1
                transports_sel = self.collect_innercity_transport(
                    query["target_city"],
                    current_position,
                    poi_plan["back_transport"]["From"],
                    current_time,
                    trans_type_sel,
                )
                if not isinstance(transports_sel, list):
                    self.backtrack_count += 1
                    print("inner-city transport error, backtrack...")
                    continue

                plan[current_day]["activities"] = self.add_intercity_transport(
                    plan[current_day]["activities"],
                    poi_plan["back_transport"],
                    innercity_transports=transports_sel,
                    tickets=self.query["people_number"],
                )

                res_bool, res_plan = self.constraints_validation(
                    query, plan, poi_plan
                )

                if res_bool:
                    return True, res_plan
                else:
                    plan[current_day]["activities"].pop()
                    self.backtrack_count += 1

                    print(
                        "Back-transport, but constraints_validation failed, backtrack..."
                    )
                    return False, plan
        elif poi_type == "hotel":

            if not self.close_day_allowed(plan, poi_plan, current_day):
                candidates_type.remove("hotel")
                continue

            hotel_sel = poi_plan["accommodation"]

            # transports_ranking = self.ranking_innercity_transport(current_position, hotel_sel["name"], current_day, current_time)
            transports_ranking = self.innercity_transports_ranking_from_query

            for trans_type_sel in transports_ranking:
                self.search_nodes += 1
                if hotel_sel["name"] == current_position:
                    transports_sel = []
                    arrived_time = current_time
                else:
                    transports_sel = self.collect_innercity_transport(
                        query["target_city"],
                        current_position,
                        hotel_sel["name"],
                        current_time,
                        trans_type_sel,
                    )
                    if not isinstance(transports_sel, list):
                        self.backtrack_count += 1
                        print("inner-city transport error, backtrack...")
                        continue

                    if len(transports_sel) == 0:
                        arrived_time = current_time
                    else:
                        arrived_time = transports_sel[-1]["end_time"]


                plan = self.add_accommodation(
                    current_plan=plan,
                    hotel_sel=hotel_sel,
                    current_day=current_day,
                    arrived_time=arrived_time,
                    required_rooms=self.required_rooms,
                    transports_sel=transports_sel,
                )

                new_time = "00:00"
                new_position = hotel_sel["name"]

                success, plan = self.dfs_poi(
                    query, poi_plan, plan, new_time, new_position, current_day + 1
                )

                if success:
                    return True, plan

                self.backtrack_count += 1
                print("Fail with the given accommodation activity, backtrack...")

                plan[current_day]["activities"].pop()
        elif poi_type in ["breakfast", "lunch", "dinner", "attraction"]:

            if poi_type in ["breakfast", "lunch", "dinner"]:

                # print(poi_info["restaurants"])
                ranking_idx = self.ranking_restaurants(
                    plan,
                    poi_plan,
                    current_day,
                    current_time,
                    current_position,
                    self.intercity_with_hotel_cost,
                )
                ranking_idx = self.reranking_restaurants_with_constraints(
                    plan,
                    poi_type,
                    current_day,
                    current_time,
                    current_position,
                    self.memory["restaurants"],
                    query,
                    ranking_idx,
                )

                for sea_i, r_i in enumerate(ranking_idx):

                    if self.search_width != None and sea_i >= self.search_width:
                        print(
                            "Out of search_width [{}], break".format(
                                self.search_width
                            )
                        )
                        break

                    res_idx = r_i

                    if not (res_idx in self.restaurants_visiting):

                        if res_idx < 0 or res_idx >= len(
                            self.memory["restaurants"]
                        ):
                            print("index error: ", res_idx, len(self.memory["restaurants"]))

                        poi_sel = self.memory["restaurants"].iloc[res_idx]

                        # transports_ranking = self.ranking_innercity_transport(current_position, poi_sel["name"], current_day, current_time)
                        transports_ranking = (
                            self.innercity_transports_ranking_from_query
                        )

                        for trans_type_sel in transports_ranking:
                            self.search_nodes += 1
                            transports_sel = self.collect_innercity_transport(
                                query["target_city"],
                                current_position,
                                poi_sel["name"],
                                current_time,
                                trans_type_sel,
                            )
                            if not isinstance(transports_sel, list):
                                self.backtrack_count += 1
                                print("inner-city transport error, backtrack...")
                                continue

                            if len(transports_sel) == 0:
                                arrived_time = current_time
                            else:
                                arrived_time = transports_sel[-1]["end_time"]


                            try:
                                plan = self.add_restaurant(
                                    plan,
                                    poi_type,
                                    poi_sel,
                                    current_day,
                                    arrived_time,
                                    transports_sel,
                                )
                            except:
                                self.backtrack_count += 1
                                print("add_restaurant failed, backtrack...")
                                continue

                            new_time = plan[current_day]["activities"][-1][
                                "end_time"
                            ]
                            new_position = poi_sel["name"]
                            self.restaurants_visiting.append(res_idx)
                            self.food_type_visiting.append(poi_sel["cuisine"])
                            success, plan = self.dfs_poi(
                                query,
                                poi_plan,
                                plan,
                                new_time,
                                new_position,
                                current_day,
                            )
                            if success:
                                return True, plan

                            self.backtrack_count += 1
                            print("add_restaurant failed, backtrack...")

                            plan[current_day]["activities"].pop()
                            self.restaurants_visiting.pop()
                            self.food_type_visiting.pop()

                            # print("res {} fail...".format(poi_sel["name"]))

            elif poi_type == "attraction":
                ranking_idx = self.ranking_attractions(
                    plan,
                    poi_plan,
                    current_day,
                    current_time,
                    current_position,
                    self.intercity_with_hotel_cost,
                )

                ranking_idx = self.reranking_attractions_with_constraints(
                    plan,
                    poi_type,
                    current_day,
                    current_time,
                    current_position,
                    self.memory["attractions"],
                    query,
                    ranking_idx,
                )

                for sea_i, r_i in enumerate(ranking_idx):

                    if self.search_width != None and sea_i >= self.search_width:
                        print(
                            "Out of search_width [{}], break".format(
                                self.search_width
                            )
                        )
                        break
                    self.search_nodes += 1
                    attr_idx = r_i
                    if not (attr_idx in self.attractions_visiting):

                        if attr_idx < 0 or attr_idx >= len(
                            self.memory["attractions"]
                        ):
                            print(attr_idx, len(self.memory["attractions"]))

                        poi_sel = self.memory["attractions"].iloc[attr_idx]
                        # print(current_position, poi_sel["name"])

                        # transports_ranking = self.ranking_innercity_transport(current_position, poi_sel["name"], current_day, current_time)
                        transports_ranking = (
                            self.innercity_transports_ranking_from_query
                        )
                        for trans_type_sel in transports_ranking:
                            self.search_nodes += 1
                            transports_sel = self.collect_innercity_transport(
                                query["target_city"],
                                current_position,
                                poi_sel["name"],
                                current_time,
                                trans_type_sel,
                            )
                            if not isinstance(transports_sel, list):
                                self.backtrack_count += 1
                                print("inner-city transport error, backtrack...")
                                continue
                            if len(transports_sel) == 0:
                                arrived_time = current_time
                            else:
                                arrived_time = transports_sel[-1]["end_time"]

                            opentime, endtime = (
                                poi_sel["opentime"],
                                poi_sel["endtime"],
                            )
                            # too late
                            if time_compare_if_earlier_equal("21:00", arrived_time):
                                self.backtrack_count += 1
                                print("The current time is too late...")
                                continue

                            # it is closed ...
                            if time_compare_if_earlier_equal(endtime, arrived_time):
                                self.backtrack_count += 1
                                print("The attraction is closed now...")
                                continue

                            preliminary_slot = self.attraction_slot(arrived_time, opentime, endtime, 1)
                            if preliminary_slot is None:
                                continue
                            act_start_time = preliminary_slot[0]

                            if not self.allow_wait(arrived_time, act_start_time):
                                continue

                            poi_time = self.select_poi_time(
                                plan,
                                poi_plan,
                                current_day,
                                act_start_time,
                                poi_sel["name"],
                                poi_type,
                                recommended_visit_time=poi_sel["recommendmintime"]
                                * 60,
                            )
                            actual_slot = self.attraction_slot(arrived_time, opentime, endtime, poi_time)
                            if actual_slot is None:
                                continue
                            act_start_time, act_end_time = actual_slot

                            if not self.meals_possible_after(plan,poi_plan,current_day,act_end_time,poi_sel['name']):
                                self.backtrack_count += 1
                                # Exact meal/cause counters are recorded by meals_possible_after.
                                continue

                            plan[current_day]["activities"] = self.add_poi(
                                activities=plan[current_day]["activities"],
                                position=poi_sel["name"],
                                poi_type=poi_type,
                                price=int(poi_sel["price"]),
                                cost=int(poi_sel["price"])
                                * self.query["people_number"],
                                start_time=act_start_time,
                                end_time=act_end_time,
                                innercity_transports=transports_sel,
                            )
                            plan[current_day]["activities"][-1]["tickets"] = (
                                self.query["people_number"]
                            )

                            new_time = act_end_time
                            new_position = poi_sel["name"]

                            self.attractions_visiting.append(attr_idx)
                            self.spot_type_visiting.append(poi_sel["type"])
                            self.attraction_names_visiting.append(poi_sel["name"])

                            success, plan = self.dfs_poi(
                                query,
                                poi_plan,
                                plan,
                                new_time,
                                new_position,
                                current_day,
                            )

                            if success:
                                return True, plan

                            self.backtrack_count += 1
                            print("add_attraction failed, backtrack...")

                            plan[current_day]["activities"].pop()
                            self.attractions_visiting.pop()
                            self.spot_type_visiting.pop()
                            self.attraction_names_visiting.pop()

            # The last event in a day: hotel or go-back

            if current_day == query["days"] - 1:

                # go back

                if len(plan) < current_day + 1:
                    plan.append({"day": current_day + 1, "activities": []})
                self.search_nodes += 1
                # transports_ranking = self.ranking_innercity_transport(current_position, poi_plan["back_transport"]["From"], current_day, current_time)
                transports_ranking = self.innercity_transports_ranking_from_query
                for trans_type_sel in transports_ranking:
                    self.search_nodes += 1
                    transports_sel = self.collect_innercity_transport(
                        query["target_city"],
                        current_position,
                        poi_plan["back_transport"]["From"],
                        current_time,
                        trans_type_sel,
                    )
                    if not isinstance(transports_sel, list):
                        self.backtrack_count += 1
                        print("inner-city transport error, backtrack...")
                        continue

                    plan[current_day]["activities"] = self.add_intercity_transport(
                        plan[current_day]["activities"],
                        poi_plan["back_transport"],
                        innercity_transports=transports_sel,
                        tickets=self.query["people_number"],
                    )

                    res_bool, res_plan = self.constraints_validation(
                        query, plan, poi_plan
                    )

                    if res_bool:
                        return True, res_plan
                    else:
                        plan[current_day]["activities"].pop()

                        self.backtrack_count += 1

                        print(
                            "Back-transport, but constraints_validation failed, backtrack..."
                        )
                        # return False, plan

            elif self.query["days"] > 1 and self.close_day_allowed(plan, poi_plan, current_day):
                # go to hotel
                hotel_sel = poi_plan["accommodation"]
                self.search_nodes += 1
                # transports_ranking = self.ranking_innercity_transport(current_position, hotel_sel["name"], current_day, current_time)
                transports_ranking = self.innercity_transports_ranking_from_query
                for trans_type_sel in transports_ranking:
                    self.search_nodes += 1
                    transports_sel = self.collect_innercity_transport(
                        query["target_city"],
                        current_position,
                        hotel_sel["name"],
                        current_time,
                        trans_type_sel,
                    )
                    if not isinstance(transports_sel, list):
                        self.backtrack_count += 1
                        print("inner-city transport error, backtrack...")
                        continue

                    if len(transports_sel) == 0:
                        arrived_time = current_time
                    else:
                        arrived_time = transports_sel[-1]["end_time"]


                    plan = self.add_accommodation(
                        current_plan=plan,
                        hotel_sel=hotel_sel,
                        current_day=current_day,
                        arrived_time=arrived_time,
                        required_rooms=self.required_rooms,
                        transports_sel=transports_sel,
                    )

                    new_time = "00:00"
                    new_position = hotel_sel["name"]

                    success, plan = self.dfs_poi(
                        query,
                        poi_plan,
                        plan,
                        new_time,
                        new_position,
                        current_day + 1,
                    )

                    if success:
                        return True, plan
                    else:
                        self.backtrack_count += 1
                        print("Try the go back hotel, failed, backtrack...")

                        plan[current_day]["activities"].pop()

                        # return False, plan
        else:
            # raise Exception("Not Implemented.")
            print("incorrect poi type: {}".format(poi_type))
            continue

        candidates_type.remove(poi_type)
        print("try another poi type, backtrack...")

    return False, plan
