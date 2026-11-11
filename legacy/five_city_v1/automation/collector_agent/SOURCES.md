# 来源清单：置信度、查询困难度与访问状态

审阅日期：2026-10-29。本轮只读既有证据，未联网重测。下表链接是历史入口，不是可访问保证；完整域名、能力、证据路径、许可和历史计数见 `../results/p33_collection_workflow_design/seed_sources.json`。请求前查询共享SQLite；更严格的家族暂停优先。

| 来源组与历史入口 | 字段候选能力 | 访问状态 | 查询难点 |
|---|---|---|---|
| [Trip/Ctrip](https://you.ctrip.com/sight/changsha148/9013.html) | 身份、开放/价目参考、房型报价范围、时刻参考 | 家族暂停 | 挑战页；分店、票种、房型与日期绑定 |
| [高德](https://restapi.amap.com/v5/place/text) | 提供方POI绑定、GCJ02、路线估计、天气 | 家族暂停 | 历史10021；端点、入口、时刻、方式与TTL |
| [Wikidata](https://query.wikidata.org/) | 声明坐标、站线关系、别名 | 家族暂停 | 历史429；身份、行政区和运营状态仍需独立核验 |
| [OSM/Nominatim/Overpass](https://nominatim.openstreetmap.org/) | 候选身份、WGS84几何、地图声明TAG | 家族暂停 | 同名/空结果/服务政策；不能按最近点合并 |
| [Overture](https://docs.overturemaps.org/guides/places/) | 候选身份、声明几何、品类 | 家族暂停 | 许可与上游链路、同名身份；暂停范围待审阅 |
| [visitxian](https://visitxian.cn/zh-CN/places/daxingshan-temple) | 开放、票价、建议时长与主题参考 | 家族暂停 | 原文时间、运营方关系、票种范围 |
| [inQingdao](https://inqingdao.com/zh/explore/attractions/zhanqiao-pier) | 开放、票价、时长、主题参考 | 未核验 | 身份、来源时钟与适用票种；访问/解析难度未知 |
| [宁波旅游网](https://www.nbtour.com/archives/6686) | 开放、票价、时长、地点描述参考 | 未核验 | 日期精度/无时区、来源角色、适用范围 |
| [城市惠](https://www.cityhui.com/shop/21011.html) | 分店地址、餐费、菜系、开放参考 | 未核验 | 人均价与套餐价区别、分店绑定、原文时钟 |
| [同程](https://www.ly.com/hotel/hoteldetail?hotelId=51401015&inDate=2026-10-24&outDate=2026-10-25&adultsNumber=2) | 指定日期/房型/人数的价格展示及床型参考 | 未核验 | 历史模型投影需原文复核；动态页面、日期房型绑定 |
| [山东航空计划PDF](https://www.sda.cn/uploads/1/20261025hbhj.pdf) | 承运方发布时刻 | 未核验 | PDF表格、季节/航向/经停；时刻不是余票或票价 |
| [岳麓书院](https://ylsy.hnu.edu.cn/wbly/cgdn/zxdp.htm) | 本机构开放、票规、闭馆通知 | 未核验 | 需核实机构/入口与通知适用日；解析成本未知 |
| [宁波博物馆](https://www.nbmuseum.cn/) | 本馆开放、票规、闭馆通知 | 未核验 | 预约与常规开放分开；原文日期和临时公告 |
| [陕西历史博物馆](https://www.sxhm.com/guide.h) | 本馆开放、票规、闭馆通知 | 未核验 | 展厅/票种、预约、临时公告范围 |
| [ACEs会议住宿页](https://www.aces-china2026.org/Hotel_Information.html) | 会议日期、参会者协议房价与床型描述 | 未核验 | 参会资格、协议日期、房型；不能充作公众现价 |

## 怎样记录置信度

每个claim分别记录：来源是否有权描述该字段、实体/分店绑定、引文语义、来源时钟、适用范围、许可、冲突与独立来源组。运营方对自身开放时间的角色更合适，但不因此自动通过日期、票种、许可等门。上述全部来源的本轮 `accuracy_probability` 都是null，不能将历史网页数转成“95%可信”。

## 怎样记录困难度

分别保存访问限制、解析难度、上下文绑定、身份歧义与成本。访问/解析未测就是unknown；同程存档另标模型投影待审阅。尝试数、合格claim数、成功率、延迟和单位成本只能由有分母的请求账本计算。15组来源种子不代表15个独立源，也不代表15个已获准抓取的站点。

来源能力只是查找方向。逐字段门接纳的是“某段证据对某个对象/范围支持某个值”，不接纳“这个网站支持所有字段”的 blanket whitelist。历史成功、旧缓存、新批次或冷却结束均不能清除暂停。
