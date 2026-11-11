import os
from .constraint_compiler import EXTRACTION_CONTRACT, validate_extraction, template_programs
from .translation_contract import (TranslationValidationError, CODE_OUTPUT_INSTRUCTION, PROGRAM_EXAMPLES, code_list, check_constraint, output_options)
import traceback
from chinatravel.json_utils import repair_json

project_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir)
)

import json
from copy import deepcopy
from chinatravel.agent.llms import create_llm
from chinatravel.symbol_verification.concept_func import func_dict
from chinatravel.symbol_verification.dsl import execute_dsl_code
from chinatravel.agent.nesy_agent.prompts.prompts_en import NL2SL_INSTRUCTION
from chinatravel.agent.nesy_agent.ast_checker_en import HardLogicPyChecker
from chinatravel.data.load_datasets import save_json_file, load_json_file


func_docs = """
(1) day_count(plan)
Docs: Get the number of days in the plan.
Return: int
(2) people_count(plan)
Docs: Get the number of people in the plan.
Return: int
(3) start_city(plan)
Docs: Get the start city of the plan.
Return: str
(4) target_city(plan)
Docs: Get the target city of the plan.
Return: str
(5) allactivities(plan)
Docs: Get all the activities in the plan.
Return: list of activities
(6) allactivities_count(plan)
Docs: Get the number of activities in the plan.
Return: int
(7) dayactivities(plan, day)
Docs: Get all the activities in the specific day [1, 2, 3, ...].
Return: list of activities
(8) activity_cost(activity)
Docs: Get the cost of specific activity without transport cost.
Return: float
(9) activity_position(activity)
Docs: Get the position name of specific activity.
Return: str
(10) activity_price(activity)
Docs: Get the price of specific activity. The price is price per person.
Return: float
(11) activity_type(activity)
Docs: Get the type of specific activity. ['breakfast', 'lunch', 'dinner', 'attraction', 'accommodation', 'train', 'airplane']
Return: str
(12) activity_tickets(activity)
Docs: Get the number of tickets needed for specific activity. ['attraction', 'train', 'airplane']
Return: int
(13) activity_transports(activity)
Docs: Get the transport information of specific activity.
Return: list of dict
(14) activity_start_time(activity)
Docs: Get the start time of specific activity.
Return: str
(15) activity_end_time(activity)
Docs: Get the end time of specific activity.
Return: str
(16) activity_time(activity)
Docs: Get the duration of specific activity.
Return: int (minutes)
(17) innercity_transport_cost(transports)
Docs: Get the total cost of innercity transport.
Return: float
(18) poi_recommend_time(city, poi):
Docs: Get the recommend time of specific poi in the city. Only support attractions now.
Return: int (minutes)
(19) poi_distance(city, poi1, poi2):
Docs: Get the distance between two pois in the city.
Return: float (km)
(20) innercity_transport_price(transports)
Docs: Get the price of innercity transport. The price is price per person.
Return: float
(21) innercity_transport_distance(transports)
Docs: Get the distance of innercity transport.
Return: float (km)
(22) metro_tickets(transports)
Docs: Get the number of metro tickets if the type of transport is metro.
Return: int
(23) taxi_cars(transports)
Docs: Get the number of taxi cars if the type of transport is taxi. The number of taxi cars is `(people_count(plan) + 3) // 4`.
Return: int
(24) room_count(activity)
Docs: Get the number of rooms of accommodation activity.
Return: int
(25) room_type(activity)
Docs: Get the type of room of accommodation activity.
1 for single room, 2 for double room. Must be 1 or 2. Never use "double room" or "twin room" or other words but 1 or 2.
Return: int
(26) restaurant_type(activity, target_city)
Docs: Get the type of restaurant's cuisine in the target city. The return value must be in ['Yunnan cuisine', 'Tibetan cuisine', 'Northeastern Chinese cuisine', 'Barbecue', 'Asian cuisine', 'Cantonese cuisine', 'Northwestern Chinese cuisine', 'Fujian cuisine', 'Hakka cuisine', 'Fast food and casual dining', 'Sichuan cuisine', 'Taiwanese cuisine', 'Other', 'Halal cuisine', 'Snacks', 'Western cuisine', 'Vegetarian cuisine', 'Japanese cuisine', 'Jiangsu-Zhejiang cuisine', 'Hubei cuisine', 'Southeast Asian cuisine', 'Hunan cuisine', 'Beijing cuisine', 'Korean cuisine', 'Seafood', 'Middle Eastern cuisine', 'fusion cuisine', 'Teahouse', 'Bar/Pub', 'Creative Cuisine', 'buffet', 'coffee shop', 'Shanghai cuisine', 'Huizhou cuisine', 'Latin American cuisine', 'Shandong Cuisine', 'Xinjiang cuisine', 'Farmhouse cuisine', 'Hainan cuisine', 'Hot pot', 'Bakery and Desserts', 'Other Chinese Cuisine'].
Return: str
(27) attraction_type(activity, target_city)
Docs: Get the type of attraction in the target city. The return value must be in ['Museum/Memorial Hall', 'Art museum', 'Red tourism sites', 'natural scenery', 'Cultural Landscape', 'University campus', 'historical site', 'Amusement Park/Sports Entertainment', 'Garden', 'Other', 'Cultural Tourism Area', 'park', 'commercial district'].
Return: str
(28) accommodation_type(activity, target_city)
Docs: Get the feature of accommodation in the target city to judge whether it's feature meets the user's requirement. The return value must be in ["Kids' Club", 'Air purifier', 'Mountain View Room', 'Private Hot Spring Room', 'Courtyard house', 'hot spring', 'Lakeside Residence', 'e-sports hotel', 'Hot spring bathing', 'Executive Lounge', 'Charging station', 'Designer hotel', 'homestay', 'Lake View Room', 'Stunning Night Views', 'Luggage Storage', 'Chinese-style courtyard', 'Billiards Room', 'Private Pool', 'Fishing', 'Charming sea view', 'Garden Architecture', 'Old Western-style house', "Children's Pool", 'Historic Residence', 'Mahjong and Card Game Room', 'Smart Room Control', "Couple's Room", 'small and beautiful', 'Tea Room', 'Family-themed room', 'Multifunction Hall', 'Laundry room', 'inn', 'Self-operated family room', 'Parking lot', 'Recommended by the Boss', 'River view room', 'Sunbathing area', 'Self-operated entertainment room', 'Kitchen', 'Air conditioning', 'Instagrammable pool', 'Villa', 'Free parking', 'Laundry service', 'Great view from the window', 'Serviced Apartment', 'Conference Hall', 'Family Room', '24-hour front desk', 'Business Center', 'Early Park Entry', 'Farm stay', 'Smart toilet', 'Gourmet Hotel', 'Spa', 'Photogenic', 'Ocean View Room', 'Swimming Pool', 'Media Room', 'Butler Service', 'Airport shuttle service', 'Sauna', 'Robot Service', "Children's Playground", 'Fitness Room', 'Washing machine', 'Self-operated Comfort Sleep Room', 'Pet-friendly', 'e-sports room', 'Excellent location', 'Suite'].
Return: str
(29) innercity_transport_type(transports)
Docs: Get the type of innercity transport. The return value must be in ['metro', 'taxi', 'walk'].
Return: str
(30) innercity_transport_start_time(transports)
Docs: Get the start time of innercity transport.
Return: str
(31) innercity_transport_end_time(transports)
Docs: Get the end time of innercity transport.
Return: str
(32) intercity_transport_type(activity)
Docs: Get the type of intercity transport. The return value must be in ['train', 'airplane'].
Return: str
(33) innercity_transport_time(transports)
Docs: Get the duration of innercity transport.
Return: int (minutes)
(34) intercity_transport_origin(activity)
Docs: Get the origin city of intercity transport.
Return: str
(35) intercity_transport_destination(activity)
Docs: Get the destination city of intercity transport.
Return: str
"""

sl_trans_prompt = (
    """
We offer some functions below, try to translate the constraints in nature language into python code and output them in json list format.
variables:
(1) plan: a dict of the generated plan with information of the specific plan.

functions:"""
    + func_docs
    + """
You need to response in the following format:
[
    "python code block 1",
    "python code block 2",
    ...
]

Not all the constraints need to be translated into python code. Ignore them if they can not be translated into legal python code.
!!! Only `plan` variable can be used directly in the python code. Others must be defined in the python code use the functions we offer above. !!! Pay attention to the return TYPE of functions!!!
For most case, for exist constraints, you can set `result=False` at the beginning of the code, and then set `result=True` if the condition is satisfied. For all constraints, you can set `result=True` at the beginning of the code, and then set `result=False` if the condition is not satisfied.

### Attention!!!
If you find some pesucode in the nature language constraints is not defined in the functions we offer above, you must translate them into python block code with the functions we offer above. Usually, for attractions and restaurants, if the required one exists, the requirement is satisfied. However, for accommodation, people usually stay in the same hotel for the whole trip, so we need check all the accommodation activities in the plan.
###

if you find some error in nature language constraints, you need to fix them in the code block. if {'natural landscape'} <= spot_type, you need to change it to 'natural scenery' in the code block as we offer above.

Example:
nature_language:
days==2
people_number==3
cost<=3000
tickets==3
rooms==2
room_type==2
{'Beijing cuisine'}<=food_type
intercity_transport=={'train'}
{'natural scenery', 'Museum/Memorial Hall'}<=spot_type
{'Smart Room Control'}<=hotel_feature
hotel_price<=500
{'Beijing Quanjude (Qianmen Branch)'} <= restaurant_names
food_price<=100
transport_type<={'metro', 'taxi'}
{'The Palace Museum'}<=attraction_names
taxi_cars==1
answer:
[
"result=(day_count(plan)==2)",
"result=(people_count(plan)==3)",
"total_cost=0\nfor activity in allactivities(plan): total_cost+=activity_cost(activity)+innercity_transport_cost(activity_transports(activity))\nresult=(total_cost<=3000)",
"result=True\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['attraction', 'airplane', 'train'] and activity_tickets(activity)!=3: result=False\n  if innercity_transport_type(activity_transports(activity))=='metro' and metro_tickets(activity_transports(activity))!=3: result=False",
"result=True\nfor activity in allactivities(plan):\n  if innercity_transport_type(activity_transports(activity))=='taxi' and taxi_cars(activity_transports(activity))!=1: result=False",
"result=True\nfor activity in allactivities(plan):\n  if activity_type(activity)=='accommodation' and room_count(activity)!=2: result=False\n  if activity_type(activity)=='accommodation' and room_type(activity)!=2: result=False\n  if activity_type(activity)=='accommodation' and accommodation_type(activity, target_city(plan))!='Smart Room Control': result=False\n  if activity_type(activity)=='accommodation' and activity_price(activity)>500: result=False",
"restaurant_type_set = set()\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['breakfast', 'lunch', 'dinner']:\n    restaurant_type_set.add(restaurant_type(activity, target_city(plan)))\nresult=({'Beijing cuisine'}<=restaurant_type_set)",
"attraction_type_set = set()\nfor activity in allactivities(plan):\n  if activity_type(activity)=='attraction':\n    attraction_type_set.add(attraction_type(activity, target_city(plan)))\nresult=({'natural scenery', 'Museum/Memorial Hall'}<=attraction_type_set)",
"intercity_transport_set = set()\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['train', 'airplane']:\n    intercity_transport_set.add(activity_type(activity))\nresult=(intercity_transport_set=={'train'})",
"restaurant_names_set = set()\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['breakfast', 'lunch', 'dinner']:\n    restaurant_names_set.add(activity_position(activity))\nresult=({'Beijing Quanjude (Qianmen Branch)'}<=restaurant_names_set)",
"result=True\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['breakfast', 'lunch', 'dinner'] and activity_price(activity)>100: result=False",
"innercity_transport_set = set()\nfor activity in allactivities(plan):\n  innercity_transport_set.add(innercity_transport_type(activity_transports(activity)))\nresult=(innercity_transport_set<={'metro', 'taxi'})",
"attraction_names_set = set()\nfor activity in allactivities(plan):\n  if activity_type(activity)=='attraction':\n    attraction_names_set.add(activity_position(activity))\nresult=({'The Palace Museum'}<=attraction_names_set)",
]
"""
)

reflect_prompt = (
    """
we offer some functions below, try to reflect on the python code block and fix them and output in the same format.
[
"python code block 1",
"python code block 2",
...
]
We offer functions below:"""
    + func_docs
    + """
Try to fix the error in the code block and output them in json list format.
The attractions_type, restaurants_type, and accommodations_type must be in the list we offer above. You must trans the original type to !!!a similar one!!! we offer if the original type is not in the list we offer above.

For return value of activity_position(activity), it will be checked by whether the position is in the database. You need to trans it to a similar one if it is rufused with you own knowledge. Also hotel_names should be checked by activity_position(activity), not accommodation_type(activity, target_city(plan)) and so for other names.
Usually, for attractions and restaurants, if the required one exists, the requirement is satisfied. However, for accommodation, people usually stay in the same hotel for the whole trip, so we need check all the accommodation activities in the plan. Either change the function or value to make the code block correct.
You must output the whole code block. Including those constraints that are correct.
The original code block is:
"""
)


def load_example_plans(example_plans_dir="chinatravel/agent/nesy_agent/plan_for_check_en"):
    plan_for_test = {}
    plan_files = os.listdir(example_plans_dir)
    plan_files = [plan_file for plan_file in plan_files if plan_file.endswith(".json")]
    for file in plan_files:
        with open(os.path.join(example_plans_dir, file), "r", encoding="utf-8") as f:
            data = json.load(f)
            plan_for_test[int(file.split("day")[1].split(".")[0])] = data
    return plan_for_test


EXAMPLE_PLANS = load_example_plans()


def get_first_list_in_str(json_str):
    # 使用栈得到第一个合法的list
    json_str = repair_json(json_str, ensure_ascii=False)
    st = 0
    # print(json_str)
    while st < len(json_str) and json_str[st] != "[":
        st += 1
    json_str = json_str[st:]
    stack = []
    for i, c in enumerate(json_str):
        if c == "[":
            stack.append(i)
        elif c == "]":
            stack.pop()
            if not stack:
                res = json_str[: i + 1]
                return res
    return "[]"


def nl2sl_step1(query, backbone_llm):

    from .extraction_alignment import extract_with_repair
    return extract_with_repair(query,backbone_llm,NL2SL_INSTRUCTION.format(query['nature_language'])+EXTRACTION_CONTRACT)



def nl2sl_step2(query, backbone_llm):
    hard_logic=query.get('hard_logic')
    if not isinstance(hard_logic,list) or not hard_logic or any(not isinstance(c,str) for c in hard_logic):
        raise TranslationValidationError('Translation stage 2 requires nonempty hard_logic strings')
    compiled=template_programs(query)
    if all(code is not None for code in compiled):
        query['hard_logic_py']=compiled
        query['translation_program_sources']=['template']*len(compiled)
        query.pop('translation_format_error',None)
        return query
    content='Translate symbolic requirements into validation programs using only these documented functions.\n'+func_docs+PROGRAM_EXAMPLES+CODE_OUTPUT_INSTRUCTION+'\nConstraints:\n'+'\n'.join(hard_logic)+'\nOriginal query:\n'+query['nature_language']+'\nanswer:\n'
    response=backbone_llm([{'role':'user','content':content}],one_line=False,json_mode=True,**output_options(backbone_llm,len(hard_logic)))
    return _store_programs(query,response)


def _store_programs(query,response):
    query['translation_raw_response']=response
    try:
        programs=code_list(response)
        templates=template_programs(query)
        if len(programs)!=len(templates):
            raise TranslationValidationError('Translation must return one program per original constraint')
        query['hard_logic_py']=[fixed if fixed is not None else program for fixed,program in zip(templates,programs)]
        for index,locked in query.get('validated_programs',{}).items():
            query['hard_logic_py'][int(index)]=locked
        query['translation_program_sources']=['template' if fixed is not None else 'model' for fixed in templates]
        query.pop('translation_format_error',None)
    except TranslationValidationError as exc:
        query['hard_logic_py']=[]
        query['translation_format_error']=str(exc)
    return query



def check(query):
    run_error_list = []
    run_error_idx = []
    hard_logic_py = query.get("hard_logic_py")
    if not isinstance(hard_logic_py,list) or not hard_logic_py:
        return [query.get('translation_format_error','Translation contains no constraint programs')], [-1]

    if len(hard_logic_py) != len(query.get('hard_logic', [])):
        return ['Translation must contain exactly one program per original constraint, in order; remove invented requirements and restore missing ones'], [-1]

    if query["days"] not in EXAMPLE_PLANS:
        print("Error: days should be in [1, 2, 3, 4, 5, 6]")
        return ['Translation cannot be checked for this day count'], [-1]

    example_plan = EXAMPLE_PLANS[query["days"]]
    for idx, constraint in enumerate(hard_logic_py):
        vars_dict = deepcopy(func_dict)
        vars_dict["plan"] = deepcopy(example_plan)
        try:
            check_constraint(constraint, vars_dict)
        except Exception as e:
            if str(e) not in [
                "Failed to create Point instance from string: unknown format.",
            ]:
                requirement=query['hard_logic'][idx]
                run_error_list.append(f'Constraint {idx+1}: {requirement}\nProgram:\n{constraint}\n{type(e).__name__}: {e!r}\nUse documented function signatures; transport helpers take activity_transports(activity), a list, not a single leg.')
                run_error_idx.append(idx)
    return run_error_list, run_error_idx


def reflect_info(query, checker: HardLogicPyChecker):
    hard_logic_py = query["hard_logic_py"]

    run_error_list, run_error_idx = check(query)
    if len(run_error_list):
        return run_error_list, run_error_idx, [], []
    value_error_list = [checker.check(constraint)[0] for constraint in hard_logic_py]
    value_error_idx = [idx for idx, item in enumerate(value_error_list) if len(item)]
    value_error_list = [
        f"Constraint {idx+1}: {query['hard_logic'][idx]}\nProgram:\n{hard_logic_py[idx]}\nValue validation: {item}"
        for idx,sublist in enumerate(value_error_list) for item in sublist
    ]
    return run_error_list, run_error_idx, value_error_list, value_error_idx


def reflect(query, backbone_llm, run_error_list, value_error_list):

    content = ('Repair validation programs using only these documented functions.\n'
        +func_docs+PROGRAM_EXAMPLES+CODE_OUTPUT_INSTRUCTION
        +'\nOriginal requirements (one program each):\n'+json.dumps(query['hard_logic'],ensure_ascii=False)
        +'\nCurrent programs:\n'+json.dumps(query['hard_logic_py'],ensure_ascii=False)
        +'\nLocked validated programs (do not change):\n'+json.dumps(query.get('validated_programs',{}),ensure_ascii=False)
        +'\nValidation errors:\n'+str(run_error_list+value_error_list)
        +'\nOriginal user query:\n'+query['nature_language']+'\nanswer:\n')
    messages = [{"role": "user", "content": content}]
    res = backbone_llm(messages, one_line=False, json_mode=True, **output_options(backbone_llm,len(query['hard_logic'])))
    return _store_programs(query,res), False



def nl2sl_step3(query, backbone_llm, checker, max_trails=3):

    cnt = 0
    query["reflect_info"] = []
    query["hard_logic_py_ood"] = []
    value_error_idx = []
    run_error_idx = []
    while cnt < max_trails:
        run_error_list, run_error_idx, value_error_list, value_error_idx = reflect_info(
            query, checker
        )
        query["reflect_info"].append(
            {
                "cnt": cnt,
                "run_error_list": run_error_list,
                "value_error_list": value_error_list,
                "hard_logic_py": query["hard_logic_py"],
            }
        )
        flag = len(run_error_list + value_error_list) == 0
        if flag:
            break
        invalid=set(run_error_idx+value_error_idx)
        if len(query['hard_logic_py'])==len(query['hard_logic']) and -1 not in invalid:
            locked=query.setdefault('validated_programs',{})
            for index,code in enumerate(query['hard_logic_py']):
                if index not in invalid:locked[str(index)]=code
        query, _ = reflect(query, backbone_llm, run_error_list, value_error_list)
        # Preserve one-to-one constraint order, including identical programs.

        # if "OOD!!!" in query["hard_logic_py"]:
        #     run_error_list, run_error_idx, value_error_list, value_error_idx = (
        #         reflect_info(query, checker)
        #     )
        #     query["ood"] = True
        #     ood_idx = list(set(run_error_idx + value_error_idx))
        #     for idx in ood_idx:
        #         query["hard_logic_py_ood"].append(query["hard_logic_py"][idx])
        #     for ood_logic in query["hard_logic_py_ood"]:
        #         query["hard_logic_py"].remove(ood_logic)
        #     return query

        cnt += 1
    query["reflect_cnt"] = cnt
    run_error_list, run_error_idx, value_error_list, value_error_idx = reflect_info(
        query, checker
    )
    query["reflect_info"].append(
        {
            "cnt": cnt,
            "run_error_list": run_error_list,
            "value_error_list": value_error_list,
            "hard_logic_py": query["hard_logic_py"],
        }
    )
    if run_error_list or value_error_list:
        raise TranslationValidationError('Translation failed after bounded repairs: '+str(run_error_list+value_error_list))
    return query


def nl2sl(query, backbone_llm, checker, cache_dir="cache_hybrid"):
    file_path = os.path.join(
        project_path,
        cache_dir,
        "translation_{}_reflect".format(backbone_llm.name),
        "{}.json".format(query["uid"]),
    )
    if os.path.exists(file_path):
        query = load_json_file(file_path)
        return query
    city_list = [
        "Beijing",
        "Shanghai",
        "Nanjing",
        "Suzhou",
        "Hangzhou",
        "Shenzhen",
        "Chengdu",
        "Wuhan",
        "Guangzhou",
        "Chongqing",
    ]
    if query["target_city"] not in city_list or query["start_city"] not in city_list:
        query["hard_logic"] = []
        query["hard_logic_py"] = []
        query["ood"] = True
        return query
    query = nl2sl_step1(query, backbone_llm)
    query = nl2sl_step2(query, backbone_llm)
    query = nl2sl_step3(query, backbone_llm, checker)

    save_json_file(query, file_path)
    return query


def nl2sl_reflect(query, backbone_llm):
    city_list = [
        "Beijing",
        "Shanghai",
        "Nanjing",
        "Suzhou",
        "Hangzhou",
        "Shenzhen",
        "Chengdu",
        "Wuhan",
        "Guangzhou",
        "Chongqing",
    ]
    if "target_city" in query and "start_city" in query:
        if query["target_city"] not in city_list or query["start_city"] not in city_list:
            query["hard_logic"] = []
            query["hard_logic_py"] = []
            query["ood"] = True
            return query
    query = nl2sl_step1(query, backbone_llm)
    query = nl2sl_step2(query, backbone_llm)
    try:
        checker = HardLogicPyChecker(query["target_city"])
        query = nl2sl_step3(query, backbone_llm, checker)
        query["hard_logic_py_iter_3"] = query["hard_logic_py"]
    except TranslationValidationError:
        raise
    except Exception as e:
        raise TranslationValidationError(
            'Translation validation could not complete: '+str(e)) from e
    return query


def run(splits: str = "easy_day1", backbone_llm=None, need_check=False):
    from tqdm import tqdm

    cache_root = "cache_reflect_v1"
    splits_file = os.path.join(
        project_path, "chinatravel/evaluation/default_splits/{}.txt".format(splits)
    )
    query_dict = {}
    data_folder = os.path.join(project_path, "chinatravel/data")
    for root, dirs, files in os.walk(data_folder):
        for file in files:
            if file.endswith(".json"):
                file_path = os.path.join(root, file)
                query = load_json_file(file_path)
                uid = file.split(".json")[0]
                query_dict[uid] = query

    with open(splits_file, "r", encoding="utf-8") as f:
        query_uid_list = f.readlines()
    cache_dir = os.path.join(
        project_path, cache_root, "translation_{}_reflect".format(backbone_llm.name)
    )
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    query_list = []
    for uid in query_uid_list:
        uid = uid.strip()
        query_list.append(query_dict[uid])

    del query_dict

    for query in tqdm(query_list):
        city_list = [
            "Beijing",
            "Shanghai",
            "Nanjing",
            "Suzhou",
            "Hangzhou",
            "Shenzhen",
            "Chengdu",
            "Wuhan",
            "Guangzhou",
            "Chongqing",
        ]
        if (
            query["target_city"] not in city_list
            or query["start_city"] not in city_list
        ):
            query["hard_logic"] = []
            query["hard_logic_py"] = []
            query["ood"] = True
            file_path = os.path.join(
                project_path,
                cache_root,
                "translation_{}_reflect".format(backbone_llm.name),
                "{}.json".format(query["uid"]),
            )
            save_json_file(query, file_path)
            print("Skip query: ", query["uid"])
            continue
        checker = HardLogicPyChecker(query["target_city"])
        query = nl2sl(query, backbone_llm, checker, cache_dir=cache_root)
        if need_check:
            if not len(check(query)[0]):
                print("Run Error in query: ", query["uid"])


if __name__ == "__main__":
    splits_list = ["human"]
    # splits_list = ["easy_1209", "multi_cons"]
    # splits_list = ["cost", "food", "attraction", "hotel", "transport"]
    # splits_list = ["attraction"]
    llm = create_llm(None)
    for splits in splits_list:
        run(splits=splits, backbone_llm=llm)
