# -*- coding: utf-8 -*-

NEXT_POI_TYPE_INSTRUCTION = """
你是 ChinaTravel 本地规划器的下一活动类型选择器。任务是在程序给定的可选类型中决定先探索哪个分支，而不是独立重写整条行程。

用户需求：{}
外层已选方案（去程、返程、酒店等；不等于已经执行的完整活动历史）：{}
当前为第 {} 天，当前时间 {}，当前位置 {}。
当前可选类型 POI_type_list：{}

【输入边界】
1. 去程、返程和酒店已由外层搜索选择；当前只能选择活动类型，不能修改班次、酒店、预算或用户要求。
2. 已选酒店不表示已经入住，已选返程不表示已经返程。未提供的历史活动、累计费用、景点数量和路线耗时必须保持未知，不要自行补全。
3. POI_type_list 是当前仍可探索的分支。不在列表中的类型可能已安排，也可能已在回溯中尝试失败；不能仅据此断言已经用过餐或完成了某项活动。
4. 只使用本次列表中原样出现的类型。具体景点、餐馆和路线由后续模块选择并验证，不要编造地点、营业时间、距离、价格或未来可行性。

【必须理解的本地执行语义】
- attraction：增加景点。原版通常按90分钟安排，可能受闭馆时间截短；不能假设只逛几分钟就能赶上下一项活动。
- lunch：午餐通常60分钟。最早11:00开始，必须在13:00之前开始；提前到达可能等待至11:00。仍需满足餐馆营业时间和实际交通条件。
- dinner：晚餐通常60分钟。最早17:00开始，必须在20:00之前开始；提前到达可能等待至17:00。仍需满足餐馆营业时间和实际交通条件。
- hotel：前往已选酒店并结束当天。住宿记录持续到24:00，随后进入次日；不是短暂寄存行李、午休或入住后继续当天游玩的操作。
- 早餐通常由程序在次日08:00–08:30加入，不是当前可自由添加的类型，也不能替代午餐或晚餐。
- back-intercity-transport：前往已选返程班次的出发站或机场并结束旅行，不是回酒店。必须预留实际接驳时间，不能更改返程班次。
- 最后一天距返程出发不超过180分钟时，现有程序会直接选择返程。更早安排活动时，也要考虑景点停留、用餐和接驳会占用余量。
- 当前时间达到23:00的搜索状态会被程序剪枝，应提前为结束当天和前往酒店留出余量。

【推荐优先级】
1. 优先遵守用户硬要求、当前候选列表和已选城际班次的时间边界。列表允许某个类型，不代表此刻选择它就一定可行。
2. lunch 仍在列表且已到午餐时段时，优先避免错过13:00的开始截止；临近截止时不要再选择需要约90分钟的景点。13:00及之后不要假设还能正常新增午餐。
3. dinner 仍在列表且已到晚餐时段时，优先避免错过20:00的开始截止；20:00及之后不要假设还能正常新增晚餐。
4. 非返程紧迫状态下，白天仍有充足时间时，不要只因酒店已选好就选 hotel。用户要求“轻松”应理解为适量、就近、有正常用餐的活动，而不是清晨入住后整天空白。
5. 过早选择餐饮可能造成长等待；在不挤占用餐和返程时间的前提下，可以先探索景点。不要在缺少路线信息时编造能赶到餐馆或车站的具体分钟数。
6. 尽量减少长通勤、长步行、来回折返、为了吃饭绕远以及过紧或过松的节奏。这些是偏好，不是新增硬限制；具体软惩罚由评分器计算，本步骤不能宣称已经算出完整路线分数。
7. 当前只决定优先探索顺序；后续搜索失败可以回溯，不要用虚构的历史或未经验证的断言掩盖不确定性。

只输出以下两行，不要使用代码块、列表或追加其他 Type 行：
Thought: 用一两句说明选择依据，引用真实当前时间、用户要求或明确的本地规则，不编造活动历史。
Type: POI_type_list 中一个原样的小写类型字符串
"""

INTERCITY_TRANSPORT_GO_INSTRUCTION = """
    You are a travel planning assistant. 
    The user's requirements are: {user_requirements}. 
    Now let's plan the journey from the start city to the target city.
    The available transport options are: 
    {transport_info} 
    Your task is to rank all available intercity transport options based on the user's needs and the provided transport information. Consider the following factors:
    1. User preferences (e.g., type, comfort, cost, speed). 
    2. Availability and reliability of the transport options.

    Please provide a ranking list of all transport options based on the user's preferences. 
    
    For trains, include the TrainID.
    For flights, include the FlightID. 

    Your response should follow this format:
    
    Thought: [Your reasoning for selecting the transport options]
    IDList: [List of all IDs ranked by preference, where each ID is either a TrainID or FlightID, formatted as a Python list. The list should contain a maximum of 30 elements.]
    """

INTERCITY_TRANSPORT_BACK_INSTRUCTION = """
    You are a travel planning assistant. 
    The user's requirements are: {user_requirements}. 
    Now let's plan the return journey from the target city back to the start city.
    The available transport options are:
    {transport_info} 
    
    Additionally, here is the transport information for the start-to-target journey:
    {selected_go_info}

    Your task is to rank all available intercity transport options for the return journey based on the user's needs and the provided transport information. Consider the following factors:
    1. User preferences (e.g., type, comfort, cost, speed).
    2. Availability and reliability of the transport options.
    3. Consistency with the start-to-target journey (e.g., using the same mode of transport if preferred).
    4. Ensuring sufficient time for sightseeing and leisure activities in the target city. 
    
    Please provide a ranking list of all transport options based on the user's preferences. 
    
    For trains, include the TrainID.
    For flights, include the FlightID. 
    
    Your response should follow this format:
    
    Thought: [Your reasoning for ranking the transport options]
    IDList: [List of all IDs ranked by preference, where each ID is either a TrainID or FlightID, formatted as a Python list. The list should contain a maximum of 30 elements.]
    """

HOTEL_RANKING_INSTRUCTION = """
    You are a travel planning assistant. 
    The user's requirements are: {user_requirements}. 
    Now let's select a suitable hotel in the target city.
    The available hotel options are:
    {hotel_info} 
    
    Your task is to rank all available hotel options based on the user's needs and the provided hotel information. Consider the following factors:
    1. User preferences (e.g., comfort, cost, location).
    2. Hotel features.
    3. Room price per night.
    4. Number of beds per room (numbed=2 for double beds, numbed=1 for single beds).
    5. Proximity to key attractions or points of interest in the target city.
    
    Additionally, keep in mind that the user's budget is allocated across multiple expenses, including intercity transportation and daily meals. Ensure that the hotel recommendations fit within the remaining budget constraints after accounting for these costs. Note that the price provided for each hotel is the cost per night per room. If the user has provided a specific budget requirement, ensure that the total cost of the hotel stay, including intercity transportation and daily meals, does not exceed this budget. Leave sufficient space in the budget for daily meals and other travel expenses.

    Please provide a ranking list of all hotel options based on the user's preferences. 
    
    For each hotel, include the name. 
    
    Your response should follow this format:
    
    Thought: [Your reasoning for ranking the hotel options]
    HotelNameList: [List of all Hotel name ranked by preference, formatted as a Python list]

    Example:
    Thought: Based on the user's preference for comfort and proximity to key attractions, the hotels are ranked as follows:
    HotelNameList: ["hotel1", "hotel2", ...]

    """
ROOMS_PLANNING_INSTRUCTION = """
    You are a travel planning assistant. 
    The user's requirements are: {user_requirements}. 
    
    Your task is to extract the following information from the user's requirements:
    1. Number of rooms requested.
    2. Number of beds per room.
    
    If the user's requirements do not specify the number of rooms or the type of room, default to -1 for both values.
    
    Room types and corresponding bed counts:
    - Single bed room: 1 bed
    - Double bed room: 2 beds
    - Twin room: 2 beds
    - King bed room: 1 bed
    
    Your response should follow this format:
    
    Thought: [Your reasoning for extracting the information]
    RoomInfo: [Number of rooms, Number of beds per room]
    """


BUDGETS_INSTRUCTION = """
    You are a travel planning assistant. 
    The user's requirements are: {user_requirements}. 
    
    Your task is to extract the budget information from the user's input. The budget should be a numerical value in the same currency as mentioned in the input.
    
    If the user's requirements do not specify the number of rooms or the type of room, default to -1 for the value.
    
    Please output the budget as a single number.
    
    Your response should follow this format:
    
    Budget: [Extracted budget as a number]
    """

INNERCITY_TRANSPORTS_SELECTION_INSTRUCTION = """
    You are a travel planning assistant. 
    The user's requirements are: {user_requirements}. 
    
    Your task is to extract the preferred mode of urban transportation from the user's requirements and rank the following transportation options based on user preferences:
    1. Metro
    2. Taxi
    3. Walk
    
    The user's requirements may specify a preferred mode of transportation or provide hints about their preferences. If a specific mode is mentioned, only include that mode in the ranking. If no specific mode is mentioned, rank the options based on common sense and typical user preferences, with the following default ranking: ["metro", "taxi", "walk"]

    Your response should follow this format:
    
    Thought: [Your reasoning for ranking the transportation options]
    TransportRanking: [List of transportation options ranked by preference, formatted as a Python list]
    """
ATTRACTION_RANKING_INSTRUCTION = """
    You are a travel planning assistant. 
    The user's requirements are: {user_requirements}. 
    The attraction info is:
    {attraction_info}
    The past cost for intercity transportation and hotel accommodations is: {past_cost}.
    
    Your task is to select and rank attractions based on the user's needs and the provided attraction information. Consider the following factors:
    1. Attraction name
    2. Attraction type
    3. Location
    4. Recommended duration
    
    Additionally, keep in mind that the user's budget is allocated across multiple expenses, including intercity transportation and hotel accommodations. Ensure that the attraction recommendations fit within the remaining budget constraints after accounting for the past cost.
    
    For each day, recommend at least 8 attractions, combining attractions for all days together. To ensure a comprehensive list, consider a larger pool of candidates and prioritize diversity in attraction type and location.
    
    Your response should follow this format:
    
    Thought: [Your reasoning for ranking the attractions]
    AttractionNameList: [List of attraction names ranked by preference, formatted as a Python list]

    Example:
    Thought: Based on the user's preference for historical sites and natural attractions, the attractions are ranked as follows:
    AttractionNameList: ["Attraction1", "Attraction2", ...]
    """

RESTAURANT_RANKING_INSTRUCTION = """
    You are a travel planning assistant. 
    The user's requirements are: {user_requirements}. 
    The restaurant info is:
    {restaurant_info}
    The past cost for intercity transportation and hotel accommodations is: {past_cost}.
    
    Your task is to select and rank restaurants based on the user's needs and the provided restaurant information. Consider the following factors:
    1. Restaurant name
    2. Cuisine type
    3. Price range
    4. Recommended food
    
    Additionally, keep in mind that the user's budget is allocated across multiple expenses, including intercity transportation and hotel accommodations. Ensure that the restaurant recommendations fit within the remaining budget constraints after accounting for the past cost. 
    Note that the price range provided for each restaurant is the average cost per person per meal, the remaining budget must cover the cost of three meals per day for {days} days.
    
    For each day, recommend at least 6 restaurants, combining restaurants for all days together.  
    
    Your response should follow this format:
    
    Thought: [Your reasoning for ranking the restaurants]
    RestaurantNameList: [List of restaurant names ranked by preference, formatted as a Python list]
    """


SELECT_POI_TIME_INSTRUCTION = """
    You are a travel planning assistant. 
    The user's requirements are: {user_requirements}. 
    Current travel plans are: {current_travel_plans}. 
    Today is {current_date}, current time is {current_time}, current visiting POI is {current_poi}, and its type is {poi_type}.
    The recommended visit time for the current POI is {recommended_visit_time} minutes.
    
    The user has the following time constraints:
    - Lunch time: 11:00-13:00
    - Dinner time: 17:00-20:00
    - Return to hotel by 23:00 (if not the last day of the trip)
    - If today is the last day of the trip, the return transport (train/flight) starts at {back_transport_time}.
    
    Your task is to select the time for the current POI based on the user's needs, current travel plans, and the provided information. Consider the following factors:
    1. User preferences
    2. Current travel plans
    3. POI type
    4. Recommended visit time for the current POI
    5. Time constraints for lunch, dinner, and return to hotel (if not the last day)
    6. If today is the last day, the return transport time
    
    The default value for the POI visit time is 90 minutes and can be adjusted based on the user's needs.
    
    Your response should follow this format:
    
    Thought: [Your reasoning for selecting the POI visit time]
    Time: [Time in minutes (Just INT value)]
    """

nl2sl_prompt = """
You need to extract start_city, target_city, days, people_number from the nature language query and transform the nature language query to hard_logic.
Classify every requirement before extraction. Put mandatory requirements in hard_logic.
Put preferences (最好, 尽量, 尽可能, 优先, 主要, prefer, mainly, primarily,
as much as possible) in soft_logic, with separate soft_logic_evidence.
Evidence must quote the complete relevant clause, including modifiers and negations.
Return hard_logic_evidence and soft_logic_evidence as lists of objects with
constraint and source. Never harden a preference or weaken a mandatory limit.
Explicit room counts and bed counts must both be retained. A king/double bed
or 大床房 has one bed (room_type==1), twin/双床房 has two (room_type==2).
Occupancy labels 单人房/双人间 alone do not establish bed count.
Only hard_logic is compiled into feasibility checking programs.
There are 16 hard_logic(vavarname)
(1) days: must be equal to the number of days user wants to travel.
"days==n" means the user wants to travel n days.
(2) people_number: must be equal to the number of people traveling.
"people_number==n" means n people are traveling.
(3) cost: must be less than or equal to the budget user offers.
"cost<=n" means the cost of the trip is less than or equal to n.
(4) tickets: a int value of the number of tickets user needs to buy.
"tickets==n" means the user needs to buy n tickets. 
(5) rooms: a int value of the number of rooms user needs to book.
"rooms==n" means the user wants to book n rooms.
(6) room_type: the number of beds in each room user wants to book.
"room_type==n" means the user wants to book n beds in each room.
(7) hotel_feature: a set of the features of the hotel user wants to book, must in ['儿童俱乐部', '空气净化器', '山景房', '私汤房', '四合院', '温泉', '湖畔美居', '电竞酒店', '温泉泡汤', '行政酒廊', '充电桩', '设计师酒店', '民宿', '湖景房', '动人夜景', '行李寄存', '中式庭院', '桌球室', '私人泳池', '钓鱼', '迷人海景', '园林建筑', '老洋房', '儿童泳池', '历史名宅', '棋牌室', '智能客控', '情侣房', '小而美', '特色 住宿', '茶室', '亲子主题房', '多功能厅', '洗衣房', '客栈', '自营亲子房', '停车场', 'Boss推荐', '江河景房', '日光浴场', '自营影音房', '厨房', '空调', '网红泳池', '别墅', '免费停车', '洗衣服务', '窗外好景', '酒店公寓', '会议厅', '家庭房', '24小时前台', '商务中心', '提前入园', '农家乐', '智能马桶', '美食酒店', 'SPA', '拍照出片', '海景房', '泳池', '影音房', '管家服务', '穿梭机场班车', '桑拿', '机器人服务', '儿童乐园', '健身室', '洗衣机', '自营舒睡房', '宠物友好', '电竞房', '位置超好', '套房'].
"{'A'}<=hotel_feature" means the hotel user wants to book has feature A.
(8) hotel_price: must be less than or equal to the hotel price user offers(average price per night).
"hotel_price<=n" means the price of the hotel is less than or equal to n.
(9) intercity_transport: a set of the intercity transportations, must in ['train','airplane'].
"intercity_transport=={'train'}" means the user wants to take a train to the destination.
(10) transport_type: a set of the transport types, must in ['metro','taxi','walk'].
"transport_type<={'A'}" means the user wants to take transport A in the city.
(11) spot_type: a set of the spot types user wants to visit, must in ['博物馆/纪念馆', '美术馆/艺术馆', '红色景点', '自然风光', '人文景观', '大学校园', '历史古迹', '游乐园/体育娱乐', '图书馆', '园林', '其它', '文化旅游区', '公园', '商业街区'].
"{'A', 'B'}<=spot_type" means the user wants to visit spot A and B.
(12) attraction_names: a set of the attraction names user wants to visit.
"{'A', 'B'}<=attraction_names" means the user wants to visit attraction A and B.
(13) restaurant_names: a set of the restaurant names user wants to visit.
"{'A', 'B'}<=restaurant_names" means the user wants to visit restaurant A and B.
(14) hotel_names: a set of the hotel names user wants to book.
"{'A'}<=hotel_names" means the user wants to book hotel A.
(15) food_type: a set of the food types user wants to enjoy, must in ['云南菜', '西藏菜', '东北菜', '烧烤', '亚洲菜', '粤菜', '西北菜', '闽菜', '客家菜', '快餐简餐', '川菜', '台湾菜', '其他', '清真菜', '小吃', '西餐', '素食', '日本料理', '江浙菜', '湖北菜', '东南亚菜', '湘菜', '北京菜', '韩国料理', '海鲜', '中东料理', '融合菜', '茶馆/茶室', '酒吧/酒馆', '创意菜', '自助餐', '咖啡店', '本帮菜', '徽菜', '拉美料理', '鲁菜', '新疆菜', '农家菜', '海南菜', '火锅', '面包甜点', '其他中餐'].
"{'A', 'B'}<=food_type" means the user wants to enjoy food A and B.
(16) food_price: must be less than or equal to the food price user offers(average price per meal).
"food_price<=n" means the price of the food is less than or equal to n.
Your response must be in legal json format. Pay attention to the format of the hard_logic and the examples below.
(17) taxi_cars: a int value of the number of cars user needs to take. it can be calculated by `(people_number+3)//4`.
(18) activity_start_time: the start time of the activity.
(19) activity_end_time: the end time of the activity.
(20) activity_time: the duration of the activity.
Do not infer rooms or beds for any trip length. Preserve explicitly requested room counts and bed types.
If you find some constraints are not in those mentioned above, you can add them to the hard_logic.
"""

nl2sl_example = "Examples:\n"

nl2sl_example_1 = """
nature_language: 当前位置上海。我和女朋友打算去苏州玩两天，预算1300元，希望酒店每晚不超过500元，开一间单床房。请给我一个旅行规划。
Answer: {'start_city': "上海", 'target_city': "苏州", 'days': 2, 'people_number': 2, 'hard_logic':  ['days==2', 'people_number==2', 'cost<=1300', 'hotel_price<=500', 'tickets==2', 'rooms==1', 'room_type==1', 'taxi_cars==1']}
"""
nl2sl_example_2 = """
nature_language: 当前位置上海。我们三个人打算去北京玩两天，想去北京全聚德(前门店)吃饭，预算6000元，开两间双床房。请给我一个旅行规划。
Answer: {'start_city': "上海", 'target_city': "北京", 'days': 2, 'people_number': 3, 'hard_logic': ['days==2', 'people_number==3', 'cost<=6000', "{'北京全聚德(前门店)'} <= restaurant_names", 'tickets==3', 'rooms==2', 'taxi_cars==1','room_type==2']}
"""
nl2sl_example_3 = """
nature_language: 当前位置重庆。我一个人想去杭州玩2天，坐高铁（G），预算3000人民币，想去自然风光景点，住一间单床且有智能客控的酒店，人均每顿饭不超过100元，尽可能坐地铁，请给我一个旅行规划。
Answer: {'start_city': '重庆', 'target_city': '杭州', 'days': 2, 'people_number': 1, 'hard_logic': ['days==2', 'people_number==1', 'cost<=3000', 'tickets==1', 'rooms==1', 'room_type==1', "intercity_transport=={'train'}", "{'自然风光'}<=spot_type", "{'智能客控'}<=hotel_feature", 'food_price<=100', "train_type=={'G'}"], 'soft_logic': ["transport_type<={'metro'}"], 'soft_logic_evidence': [{'constraint': "transport_type<={'metro'}", 'source': '尽可能坐地铁'}]}
"""
nl2sl_example_4 = """
nature_language: 当前位置苏州。我和我的朋友想去北京玩3天，预算8000人民币，坐火车去，想吃北京菜，想去故宫博物院看看，住的酒店最好有管家服务。
Answer: {'start_city': '苏州', 'target_city': '北京', 'days': 3, 'people_number': 2, 'hard_logic': ['days==3', 'people_number==2', 'cost<=8000', 'tickets==2', 'taxi_cars==1', "intercity_transport=={'train'}", "{'北京菜'}<=food_type", "{'故宫博物院'}<=attraction_names"], 'soft_logic': ["{'管家服务'}<=hotel_feature"], 'soft_logic_evidence': [{'constraint': "{'管家服务'}<=hotel_feature", 'source': '住的酒店最好有管家服务'}]}
"""

nl2sl_example_5 = """
nature_language: 当前位置上海。我和女朋友打算去苏州玩两天，预算1300元，希望酒店每晚不超过
"""


class NL2SL_INSTRUCTION:
    def __init__(self):
        pass

    @classmethod
    def format(cls, nature_language):
        return (
            nl2sl_prompt
            + nl2sl_example
            + nl2sl_example_1
            + nl2sl_example_2
            + nl2sl_example_3
            + nl2sl_example_4
            + "\nExamples End."
            + "\nnature_language: "
            + nature_language
            + "\nlogical_constraints: "
            + nature_language
            + "\n"
        )


nl2sl_prompt_v2 = """
You need to extract start_city, target_city, people_number, days from the nature language query and transform the nature language query to hard_logic. 
You need to extract the hard_logic from the nature language query and format them as python code. Each hard_logic should be a python block and the final result should be a boolean value.
We will offer you some atomic variables and funtions to help you transform the nature language query to hard_logic. You can combine them to form the hard_logic as long as they are legal python expressions.

!!! You must store the final result in the variable `result` so that we can get the final result from the variable `result`.!!!
!!! Note that the you must select activity with its type for some hard_logic.!!!

variables:
(1) plan: a dict of the generated plan with information of the specific plan.

functions:
(1) day_count(plan)
Docs: Get the number of days in the plan.
Return: int
(2) people_count(plan)
Docs: Get the number of people in the plan.
Return: int
(3) target_city(plan)
Docs: Get the target city of the plan.
Return: str
(4) allactivities(plan)
Docs: Get all the activities in the plan.
Return: list of activities
(5) activity_cost(activity)
Docs: Get the cost of specific activity without transport cost.
Return: float
(6) activity_position(activity)
Docs: Get the position name of specific activity.
Return: str
(7) activity_type(activity)
Docs: Get the type of specific activity. ['breakfast', 'lunch', 'dinner', 'attraction', 'accommodation', 'train', 'airplane']
Return: str
(8) activity_tickets(activity)
Docs: Get the number of tickets needed for specific activity. ['attraction', 'train', 'airplane']
Return: int
(9) activity_transports(activity)
Docs: Get the transport information of specific activity.
Return: list of dict
(10) activity_start_time(activity)
Docs: Get the start time of specific activity.
Return: str
(11) activity_end_time(activity)
Docs: Get the end time of specific activity.
Return: str
(12) innercity_transport_cost(transports)
Docs: Get the total cost of innercity transport.
Return: float
(13) metro_tickets(transports)
Docs: Get the number of metro tickets if the type of transport is metro.
Return: int
(14) taxi_cars(transports)
Docs: Get the number of taxi cars if the type of transport is taxi. We assume that the number of taxi cars is `(people_count(plan) + 3) // 4`.
Return: int
(15) room_count(activity)
Docs: Get the number of rooms of accommodation activity.
Return: int
(16) room_type(activity)
Docs: Get the type of room of accommodation activity. 1: 大床房, 2: 双床房
Return: int
(17) restaurant_type(activity, target_city)
Docs: Get the type of restaurant's cuisine in the target city. We only support ['云南菜', '西藏菜', '东北菜', '烧烤', '亚洲菜', '粤菜', '西北菜', '闽菜', '客家菜', '快餐简餐', '川菜', '台湾菜', '其他', '清真菜', '小吃', '西餐', '素食', '日本料理', '江浙菜', '湖北菜', '东南亚菜', '湘菜', '北京菜', '韩国料理', '海鲜', '中东料理', '融合菜', '茶馆/茶室', '酒吧/酒馆', '创意菜', '自助餐', '咖啡店', '本帮菜', '徽菜', '拉美料理', '鲁菜', '新疆菜', '农家菜', '海南菜', '火锅', '面包甜点', '其他中餐'].
Return: str
(18) attraction_type(activity, target_city)
Docs: Get the type of attraction in the target city. We only support ['博物馆/纪念馆', '美术馆/艺术馆', '红色景点', '自然风光', '人文景观', '大学校园', '历史古迹', '游乐园/体育娱乐', '图书馆', '园林', '其它', '文化旅游区', '公园', '商业街区'].
Return: str
(19) accommodation_type(activity, target_city)
Docs: Get the feature of accommodation in the target city. We only support ['儿童俱乐部', '空气净化器', '山景房', '私汤房', '四合院', '温泉', '湖畔美居', '电竞酒店', '温泉泡汤', '行政酒廊', '充电桩', '设计师酒店', '民宿', '湖景房', '动人夜景', '行李寄存', '中式庭院', '桌球室', '私人泳池', '钓鱼', '迷人海景', '园林建筑', '老洋房', '儿童泳池', '历史名宅', '棋牌室', '智能客控', '情侣房', '小而美', '特色 住宿', '茶室', '亲子主题房', '多功能厅', '洗衣房', '客栈', '自营亲子房', '停车场', 'Boss推荐', '江河景房', '日光浴场', '自营影音房', '厨房', '空调', '网红泳池', '别墅', '免费停车', '洗衣服务', '窗外好景', '酒店公寓', '会议厅', '家庭房', '24小时前台', '商务中心', '提前入园', '农家乐', '智能马桶', '美食酒店', 'SPA', '拍照出片', '海景房', '泳池', '影音房', '管家服务', '穿梭机场班车', '桑拿', '机器人服务', '儿童乐园', '健身室', '洗衣机', '自营舒睡房', '宠物友好', '电竞房', '位置超好', '套房'].
Return: str
(20) innercity_transport_type(transports)
Docs: Get the type of innercity transport. We only support ['metro', 'taxi', 'walk'].
Return: str
(21) innercity_transport_tickets(activity)
Docs: Get the number of tickets of innercity transport.
Return: int

response in json format as below:
"""

example_nl2sl_v2 = """
Example:

nature_language:
当前位置上海。我一个人想坐火车去杭州玩一天，预算1500人民币，请给我一个旅行规划。
answer:
{
"start_city": "上海",
"target_city": "杭州",
"days": 1,
"people_number": 1,
"hard_logic_py": ["result=(day_count(plan)==1)","result=(people_count(plan)==1)","total_cost=0 \nfor activity in allactivities(plan): total_cost+=activity_cost(activity)+innercity_transport_cost(activity_transports(activity))\nresult=(total_cost<=1500)","result=True\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['attraction', 'airplane', 'train'] and activity_tickets(activity)!=1: result=False\n  if innercity_transport_type(activity_transports(activity))=='metro'and metro_tickets(activity_transports(activity))!=1: result=False","result=True\nfor activity in allactivities(plan):\n  if innercity_transport_type(activity_transports(activity))=='taxi'and taxi_cars(activity_transports(activity))!=1: result=False","intercity_transport_set=set()\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['train', 'airplane']: intercity_transport_set.add(intercity_transport_type(activity))\nresult=(intercity_transport_set=={'train'})"],

}

nature_language:
当前位置广州。我们三个人想去成都玩3天，只坐地铁，住成都明悦大酒店，请给我们一个旅行规划。
answer:
{
"start_city": "广州",
"target_city": "成都",
"days": 3,
"people_number": 3,
"hard_logic_py": [
"result=(day_count(plan)==3)","result=(people_count(plan)==3)","result=True\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['attraction', 'airplane', 'train'] and activity_tickets(activity)!=3: result=False\n  if innercity_transport_type(activity_transports(activity))=='metro'and metro_tickets(activity_transports(activity))!=3: result=False","result=True\nfor activity in allactivities(plan):\n  if innercity_transport_type(activity_transports(activity))=='taxi'and taxi_cars(activity_transports(activity))!=1: result=False","accommodation_name_set=set()\nfor activity in allactivities(plan):\n  if activity_type(activity)=='accommodation': accommodation_name_set.add(activity_position(activity))\nresult=({'成都明悦大酒店'}<=accommodation_name_set)","innercity_transport_set=set()\nfor activity in allactivities(plan):\n  if activity_transports(activity)!=[]: innercity_transport_set.add(innercity_transport_type(activity_transports(activity)))\nresult=(innercity_transport_set<={'metro'})"],
}

nature_language:
当前位置上海。我和朋友计划去北京玩三天，预算6000元，市内交通只使用地铁，开一间单床房。请给我一个旅行规划。
answer:
{
"start_city": "上海",
"target_city": "北京",
"days": 3,
"people_number": 2,
"hard_logic_py": ["result=(day_count(plan)==3)","result=(people_count(plan)==2)","total_cost=0 \nfor activity in allactivities(plan): total_cost+=activity_cost(activity)+innercity_transport_cost(activity_transports(activity))\nresult=(total_cost<=6000)","result=True\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['attraction', 'airplane', 'train'] and activity_tickets(activity)!=2: result=False\n  if innercity_transport_type(activity_transports(activity))=='metro'and metro_tickets(activity_transports(activity))!=2: result=False","result=True\nfor activity in allactivities(plan):\n  if innercity_transport_type(activity_transports(activity))=='taxi'and taxi_cars(activity_transports(activity))!=1: result=False","result=True\nfor activity in allactivities(plan):\n  if activity_type(activity)=='accommodation' and room_count(activity)!=1: result=False\n  if activity_type(activity)=='accommodation' and room_type(activity)!=1: result=False","innercity_transport_set=set()\nfor activity in allactivities(plan):\n  if activity_transports(activity)!=[]: innercity_transport_set.add(innercity_transport_type(activity_transports(activity)))\nresult=(innercity_transport_set<={'metro'})"],
}

nature_language:
"""


class NL2SL_INSTRUCTION_V2:
    def __init__(self):
        pass

    @classmethod
    def format(cls, nature_language):
        nature_language = nature_language.strip().replace("\n", "")
        return nl2sl_prompt_v2 + example_nl2sl_v2 + nature_language + "\nanwser:"


if __name__ == "__main__":
    import os

    from chinatravel.agent.nesy_agent.prompts import NL2SL_INSTRUCTION_V2
    from chinatravel.agent.llms import create_llm

    llm = create_llm(None)

    # nature_language = """当前位置广州。我和朋友两个人想去深圳玩3天，想吃八合里牛肉火锅(东园店)，请给我们一个旅行规划。"""
    # nature_language = """当前位置苏州。我两个人想去杭州玩2天，预算4000人民币，住一间大床房，期间打车，酒店最好有窗外好景，想去雷峰塔看一下，请给我一个旅行规划。"""
    nature_language = """当前位置苏州。我和女朋友打算去上海玩两天，坐地铁，预算1300元，希望酒店每晚不超过500元，开一间单床房。请给我一个旅行规划。"""
    print(NL2SL_INSTRUCTION_V2.format(nature_language))
    # res = llm(
    #     [{"role": "user", "content": NL2SL_INSTRUCTION_V2.format(nature_language)}],
    #     json_mode=True,
    #     one_line=False,
    # )
    # print(res)
