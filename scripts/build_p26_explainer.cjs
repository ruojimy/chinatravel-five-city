const fs = require('fs');
const path = require('path');
const PptxGenJS = require('C:/Users/xiech/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/pptxgenjs');
const root=path.resolve(__dirname,'../..');
const out=path.join(root,'output/ppt/P26_静态数据库扩展与动态检验_通俗讲解');
fs.mkdirSync(out,{recursive:true});
const pptx=new PptxGenJS();
pptx.layout='LAYOUT_WIDE';
pptx.author='研究项目工作记录';pptx.subject='静态数据扩展、动态检索检验与不足';
pptx.title='从扩充数据到可靠旅行方案';pptx.company='ChinaTravel / ShortTrip';pptx.lang='zh-CN';
pptx.theme={headFontFace:'Microsoft YaHei',bodyFontFace:'Microsoft YaHei',lang:'zh-CN'};
const C={dark:'173B36',green:'22695B',mint:'DDF0E8',orange:'C66B30',pale:'FBEEE5',white:'FFFFFF',ink:'213D38',muted:'60716C',line:'D9E4DE',gray:'E9EEEB'};
const S=pptx.ShapeType;
let spoken=[];
function text(s,t,x,y,w,h,size=20,color=C.ink,bold=false,extra={}){
 s.addText(t,{x,y,w,h,fontFace:'Microsoft YaHei',fontSize:size,color,bold,margin:0,isTextBox:true,breakLine:false,vertAlign:'mid',...extra});
}
function rect(s,x,y,w,h,fill,line=fill,r=.15){s.addShape(r?S.roundRect:S.rect,{x,y,w,h,rectRadius:r,fill:{color:fill},line:{color:line,width:.5},radius:r});}
function circ(s,t,x,y,size=.55,fill=C.green,fg=C.white){s.addShape(S.ellipse,{x,y,w:size,h:size,fill:{color:fill},line:{color:fill}});text(s,t,x,y,size,size,18,fg,true,{align:'center'});}
function title(s,t,sub){text(s,t,.65,.50,12.0,.68,30,C.dark,true);if(sub)text(s,sub,.68,1.23,11.9,.52,16,C.muted);}
function footer(s,source,n,dark=false){text(s,source,.68,7.02,11.4,.24,9,dark?'ACC7BD':C.muted);text(s,String(n).padStart(2,'0'),12.0,6.99,.6,.28,11,dark?'ACC7BD':C.muted,false,{align:'right'});}
function slide(t,sub,source='依据：报告18、19及P24/P25冻结实验记录',dark=false){const s=pptx.addSlide();s.background={color:dark?C.dark:C.white};if(!dark)title(s,t,sub);footer(s,source,pptx._slides.length,dark);return s;}
function note(s,t){s.addNotes(t);spoken.push({n:pptx._slides.length,title:t.split('。')[0],text:t});}
function takeaway(s,t,y=6.16){rect(s,.68,y,11.95,.60,C.mint);text(s,t,.92,y+.08,11.48,.42,18,C.dark,true);}
function row(s,num,heading,body,y,fill=C.green){circ(s,num,.72,y,.52,fill);text(s,heading,1.45,y-.02,10.9,.43,22,C.dark,true);text(s,body,1.45,y+.50,10.85,.64,17,C.muted);}
function nativeTable(s,headers,rows,x,y,w,widths,fontSize=17){
 const data=[headers.map(t=>({text:t,options:{bold:true,color:C.white,fill:C.green}})),...rows.map((r,i)=>r.map(t=>({text:String(t),options:{fill:i%2?C.white:'F0F6F2',color:C.ink}})))];
 s.addTable(data,{x,y,w,colW:widths,fontFace:'Microsoft YaHei',fontSize,margin:.13,border:{type:'solid',color:'FFFFFF',pt:2},rowH:.58,autoPage:false,vertAlign:'mid'});
}

// 1
{
 const s=slide('','','本次工作：新静态库扩展、P24动态检验、P25修复、P26全库分析',true);
 text(s,'从扩充数据\n到可靠旅行方案',.80,1.05,9.8,1.85,42,C.white,true);
 text(s,'静态数据库扩展与动态检验：做了什么，发现了什么',.84,3.25,11.6,.62,22,'D2E7DE');
 const xs=[.85,4.95,9.05];const ns=['30','14,057','96'];const ls=['新增城市','新库实体记录','动态检验任务'];
 xs.forEach((x,i)=>{text(s,ns[i],x,4.62,3.3,.8,44,i===2?'F1BB8C':C.white,true);text(s,ls[i],x,5.52,3.3,.42,18,'D2E7DE');});
 note(s,'这次工作的目标，是让系统能在更多城市里给出有依据的旅行方案。我们扩展了30个新城市，共14057条实体记录，又用96个任务检验动态检索能不能补上真正缺失的信息。接下来重点讲进展和不足，不把数据库变大直接当成旅行规划成功。');
}
// 2
{
 const s=slide('先弄懂：这次任务有三步','schema 可以理解为“旅行方案必须填写的结构化清单”。');
 const items=[['1','扩充静态库','先存姓名、位置、类别\n以及能找到的经营信息'],['2','动态补信息','遇到票价、时间或路线缺口\n再按具体日期和人数查询'],['3','检验方案','检查来源、价格、时间与预算\n判断是否足以支持这次旅行']];
 items.forEach((a,i)=>{const x=.8+i*4.15;circ(s,a[0],x,2.22,.65);text(s,a[1],x,3.08,3.65,.52,26,C.dark,true);text(s,a[2],x,3.92,3.58,1.04,19,C.muted);if(i<2)s.addShape(S.chevron,{x:x+3.52,y:3.10,w:.35,h:.48,fill:{color:C.line},line:{color:C.line}});});
 takeaway(s,'例如：“明天两个人去某景点”，至少要知道它是谁、何时开放、门票和怎么往返。');
 note(s,'静态库是提前存好的资料，动态检索是按当前需求再查，schema就是最终计划的填写规范。比如明天两个人去景点，光知道名字和坐标还不够，需要开放规则、价格和往返路线。三步必须衔接起来才能形成可靠方案。');
}
// 3
{
 const s=slide('静态库扩展完成了什么','新增30城，涵盖西安、厦门、长沙、昆明等；原ChinaTravel十城保留作对照。','数据：正式扩容快照v1.7；统计于2026-10-23发布快照');
 text(s,'14,057',.83,2.0,4.5,1.0,60,C.green,true);text(s,'条新库实体记录',.87,3.10,4.7,.5,24,C.dark,true);
 text(s,'主要保存了姓名、坐标和来源类别。\n所有记录通过结构与载入检查。',.87,4.12,4.5,1.0,20,C.muted);
 s.addChart(pptx.ChartType.doughnut,[{name:'实体类型',labels:['住宿','餐厅','景点'],values:[6080,4601,3376]}],{x:6.1,y:1.83,w:5.8,h:3.75,holeSize:68,showLegend:false,showTitle:false,showValue:false,chartColors:[C.green,'75A493','D9A477'],showBorder:false,showPercent:false});
 [['住宿',6080,C.green],['餐厅',4601,'75A493'],['景点',3376,'D9A477']].forEach((r,i)=>{circ(s,'',6.28+i*2.07,5.52,.21,r[2]);text(s,r[0]+' '+r[1].toLocaleString(),6.58+i*2.07,5.40,1.8,.45,16,C.ink);});
 takeaway(s,'扩展的是候选覆盖面；经营信息是否齐全，还要逐字段检查。');
 note(s,'新库一共有6080条住宿、4601条餐厅和3376条景点记录，合计14057条。数据结构检查通过，说明能加载、字段格式符合合约。但这不代表每个实体的经营事实已经核实，也不代表都能组成旅行。扩容库由13800条Overture记录和257条地图快照记录组成。');
}
// 4
{
 const s=slide('最突出的问题：关键经营信息仍很少','下图是原生字段“有值”的比例；有值仍需检查来源、日期和适用范围。','数据：P26全库字段审计 field_coverage.json；分母为各自实体类型总数');
 const bars=[['景点票价','11 / 3,376',.3258],['景点营业时间对','54 / 3,376',1.5995],['餐厅人均价','277 / 4,601',6.0204],['餐厅营业时间对','115 / 4,601',2.4995],['住宿价格','2 / 6,080',.0329],['住宿床数','167 / 6,080',2.7467]];
 text(s,'字段',.82,2.0,3.2,.35,16,C.muted);text(s,'覆盖情况',4.1,2.0,4.6,.35,16,C.muted);text(s,'有值数量',10.02,2.0,2.3,.35,16,C.muted);
 bars.forEach((b,i)=>{const y=2.60+i*.49;text(s,b[0],.82,y,3.0,.34,18);rect(s,4.08,y+.04,4.55,.20,C.gray,C.gray,0);rect(s,4.08,y+.04,Math.max(.025,4.55*b[2]/100),.20,C.orange,C.orange,0);text(s,b[2].toFixed(2)+'%',8.83,y-.01,1.03,.38,18,C.orange,true);text(s,b[1],10.05,y-.01,2.0,.38,17,C.muted);});
 takeaway(s,'名字和坐标能帮助“找到候选”，价格、营业时间和房型信息决定“能否安排”。');
 note(s,'用100%的统一底条可以直观看到缺失的程度。景点票价只有11条，营业时间对54条。餐厅人均价277条。住宿原生价格只有2条。这里统计的是原生字段，不包括所有侧层参考，所以并不是说我们完全没有其他引用。关键在于完整、适用的经营信息仍然很稀疏。');
}
// 5
{
 const s=slide('即使有数据，也有三类使用风险','这些问题会让系统“查到了内容，却仍然填不对方案”。','依据：报告18；城市未决不等于全部错城，历史报价不等于当前报价');
 row(s,'1','地点可能没对上','6,776条只有采集窗口归属。无锡窗口中也出现来源写“苏州”的实体。',2.02);
 row(s,'2','时间可能不适用','下载日期不能当事实更新时间。10份带日期房价引用在发布时已超过5分钟有效期。',3.36);
 row(s,'3','价格或房型范围不同','人均消费不是保证账单；某个双床房的配置不能代表整家酒店。',4.70,C.orange);
 note(s,'第一类是城市和实体绑定。6776条城市归属待核验，不能直接说全部错城，但直接用窗口城市抽题有风险。第二类是时效。10份房价引用在发布时已超过项目设定的300秒期限，仍能做研究参考，不能当当前可订报价。第三类是范围。票价、人均、每房每晚必须分清，床数也要绑定具体房型。');
}
// 6
{
 const s=slide('动态检验怎样设计','旧题检查已有数据里的规划能力；新题重点检查真实缺口能否补上。');
 nativeTable(s,['检验对象','主要看什么','本次证据'],[
  ['原ChinaTravel题','在冻结数据中查找和满足约束','150题LLM参与样本\n补检后118题通过'],
  ['新增城市题','能否发现缺口、请求并使用证据','30新城单城题90道\n另有6条新旧城市串联'],
  ['三层任务','easy / hard / human分层观察','每层32题，共96题\n首稿＋动态稿共192份']
 ],.77,2.13,11.8,[2.55,4.35,4.9],17);
 takeaway(s,'本次重点：残缺数据怎样得到补充，以及补回的信息能否正确影响计划。');
 note(s,'原ChinaTravel的150题是LLM和规划器共同参与的冻结沙盒实验，补检后118题通过，不能拿这个比例当现实动态成功率。新增96题来自30个新城，每城三个层次，再加6条新旧城市串联。human是研究者构造的自然表达题，不是真人采集题。同实体跨层复用，样本有关联。本轮也没有完整验证旧实体在混合扩容噪声中的抗干扰能力。');
}
// 7
{
 const s=slide('动态检索确实补回了信息，但范围有限','528个必需字段中，40个获得支持，占7.58%。这些是题内字段需求次数。','依据：P24冻结实验与P26逐字段复算；不是本次新增联网测试');
 text(s,'40 / 528',.82,1.95,5.6,.94,47,C.green,true);text(s,'获得证据支持的必需字段',.86,3.02,5.4,.5,22,C.dark,true);
 [['天气估计',24,C.green],['票价参考',8,'75A493'],['营业时间参考',8,C.orange]].forEach((r,i)=>{circ(s,String(r[1]),.88,3.85+i*.62,.45,r[2]);text(s,r[0],1.58,3.84+i*.62,3.9,.45,20);});
 s.addChart(pptx.ChartType.doughnut,[{name:'必需字段',labels:['有支持','仍无支持'],values:[40,488]}],{x:7.22,y:1.90,w:4.7,h:3.8,holeSize:75,showLegend:false,showTitle:false,showValue:false,chartColors:[C.green,C.gray],showBorder:false});
 text(s,'488',8.47,3.02,2.25,.68,38,C.orange,true,{align:'center'});text(s,'个字段仍无支持',8.13,3.80,2.9,.44,18,C.muted,false,{align:'center'});
 takeaway(s,'身份、路线耗时/费用和城际班次/费用，本轮均未补齐。');
 note(s,'动态检索新增支持40个必需字段，包括24个天气估计、8个票价参考和8个营业时间参考。这些不是verified的事实确认，也不是40个独立实体。剩下488个字段没有合格支持，身份、路线和城际都没有补齐。实际374次请求是捕获语料的网关回放，不是374次联网。源侧做了6次天气调用、8次页面尝试和4个搜索query。');
}
// 8
{
 const s=slide('为什么最后仍是0个完整方案','复核发现：即使把当时捕获语料全部提供，仍无法完整解决这96题。');
 const steps=[['先明确身份','96题均缺合格身份支持',C.orange],['再安排交通','市内路线与城际证据缺失',C.orange],['最后闭合行程','完整方案的条件仍未凑齐',C.muted]];
 steps.forEach((r,i)=>{const x=.85+i*4.18;circ(s,String(i+1),x,2.27,.62,r[2]);text(s,r[0],x,3.20,3.60,.53,26,C.dark,true);text(s,r[1],x,4.04,3.45,1.0,21,C.muted);});
 takeaway(s,'实际支持40 = 当时语料上限40；零完成率需要结合数据供给条件解释。');
 note(s,'这里是分析结果的重要转折。我们把全部捕获语料与每个必需字段逐一比较，发现上限就是40，实际也达到40。96题全部缺少合格身份来源，因此没有完整可解的正例。零完成率不能全部归因于模型，但40达到40也不能说明自主联网检索已最优，因为语料是根侧有限预选捕获的，模型只做了请求回放。');
}
// 9
{
 const s=slide('模型和算法仍暴露出两项不足','补回信息之后，还需要判断它能否使用，以及是否应该改计划。');
 text(s,'6 / 96',.85,2.0,5.3,.98,48,C.orange,true);text(s,'动态稿证据状态有误',.88,3.05,5.2,.56,25,C.dark,true);text(s,'部分旧价或被隔离信息\n仍被当成“已解决”。',.88,3.98,5.1,1.0,22,C.muted);
 text(s,'0',7.12,2.0,4.9,.98,48,C.orange,true);text(s,'活动时段或顺序的实际变化',7.15,3.05,5.2,.62,24,C.dark,true);text(s,'26题对象有改动，\n主要是引用、价格等字段。',7.15,3.98,5.1,1.0,22,C.muted);
 takeaway(s,'现有结果证明了部分“信息接入”，还没有证明有效的“证据驱动重规划”。');
 note(s,'数据不足之外，模型自身仍有问题。动态稿中6份证据状态不正确，不能把过期或隔离的参考提升为已解决。19条不可用证据交付中有4条被误用，4是交付条次数，6是问题方案数。另一个不足是26题方案对象变化，但没有实际改变时段或顺序，所以不能宣称路线或天气驱动的重规划已经有效。');
}
// 10
{
 const s=slide('已修复什么：把可靠性检查放进流程','新增字段权限、人数与总价、返程、时间窗口和预算检查。','依据：P25修复与受控反例；24题复用同一长沙快照模板，非独立城市泛化');
 nativeTable(s,['环节','修复后的要求'],[
 ['证据使用','身份、库存、房型、班次需相应验证\n天气与路线估计需匹配时间和上下文'],
 ['费用与时间','单价乘人数，往返都计费\n未知费用保留未知，检查缓冲和最晚入场'],
 ['方案状态','分开“未知”“有条件可接受”“执行已确认”\n参考价格不能变成已付款或已预约']
 ],.8,2.05,11.75,[2.35,9.4],18);
 takeaway(s,'24个受控测试正确分类24个；接纳9个，其中3合成、6真实快照条件正例。');
 note(s,'P25把部分可靠性检查实现为规则系统，并规范了实体与反馈ID。24个受控测试分类正确，但这不是24个完整成功旅行。接纳的9个里面有3个合成正例和6个真实快照条件正例，执行确认仍为0。原96份经安全投影后仍然没有变成完整旅行。另一个待修工程问题是本地哈希ID被全局新鲜度门误当业务事实，分析阶段已定位，尚未以此放松身份要求。');
}
// 11
{
 const s=slide('一个具体成果：长沙半日条件方案','两人、预算200元，计划日期为2026年10月24日；这里用于说明方法。','P25冻结交付案例；短时效路线/天气执行前须刷新，预约待完成，不代表已执行');
 const data=[['13:00','湖南省博物馆正门出发'],['14:00—16:00','游览岳麓书院'],['17:15前','计划返回原出发点']];
 data.forEach((r,i)=>{circ(s,String(i+1),.9,2.13+i*1.10,.52,i===1?C.green:'75A493');text(s,r[0],1.65,2.11+i*1.10,2.60,.48,23,C.green,true);text(s,r[1],4.34,2.11+i*1.10,7.85,.48,23);});
 rect(s,.85,5.59,11.68,.88,C.mint);text(s,'门票参考 80元 + 往返地铁估计 12元 = 92元',1.08,5.73,11.2,.51,25,C.dark,true);
 note(s,'这个案例是两个人从湖南省博物馆正门出发，去岳麓书院，再回到原门口。这里只把博物馆作为出发锚点，不包含参观博物馆。两人门票参考80元，往返地铁费用估计12元，合计投影92元，不含餐饮住宿。它说明完整证据链可以支持一个具体条件方案，但捕获的短时效信息执行前需要重查，预约没有完成，也不能称实际消费或已执行旅行。');
}
// 12
{
 const s=slide('下一步：先把完整需求做可靠，再扩大覆盖','判断改进是否有效，要同时看数据供给、检索使用和计划调整。','依据：报告18、19的后续目标；以下为待开展工作，不是已完成测试');
 row(s,'1','先修实体与表达','分清采集窗口和真实城市，绑定具体分店/入口，保留房型、产品和日历范围。',2.02);
 row(s,'2','让检索服务一条完整行程','先补身份与坐标，再查路线与报价；新证据到来后检查是否需要改时间和预算。',3.36);
 row(s,'3','补充真正可解的独立测试','包含景点、餐饮、酒店与城际，分开统计能完成、部分完成、应拒绝/澄清。',4.70,C.orange);
 note(s,'下一步不应继续只增加实体数。先解决身份和城市，分清产品与房型，再集中补全少量城市里的完整需求链。评测需要先确认哪些题真实可解，分别比较静态、动态不重规划、动态加重规划、完整证据输入。这样才能知道失败究竟因为没有数据、没有检到、用错证据，还是规划不对。本次已完成扩容、检验、部分修复和两份分析报告，重点结论是扩容覆盖增加了，但可靠信息与证据驱动规划仍需加强。');
}

async function main(){
 const file=path.join(out,'静态数据库扩展与动态检验_通俗讲解.pptx');
 await pptx.writeFile({fileName:file});
 fs.writeFileSync(path.join(out,'逐页讲解词.md'),'# 逐页讲解词\n\n'+spoken.map(a=>`## 第${a.n}页\n\n${a.text}\n`).join('\n'),'utf8');
 fs.writeFileSync(path.join(out,'制作说明.json'),JSON.stringify({slides:pptx._slides.length,file,sources:['reproduction/报告/18_新数据集质量问题与修复优先级.md','reproduction/报告/19_动态检索辅助完成残缺数据Schema的能力与不足.md','reproduction/results/p26_dataset_diagnosis/dataset_profile.json','reproduction/results/p26_dataset_diagnosis/schema_support_audit.json','reproduction/results/p24_dynamic_feedback/summary.json','reproduction/results/p25_reliable_retrieval/summary.json'],scope:'本地冻结研究结果的通俗解释；无新网络或模型测试；可编辑图形和图表，含逐页演讲备注'},null,2));
 console.log(file);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
