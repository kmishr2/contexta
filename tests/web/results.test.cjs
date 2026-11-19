const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('app/web/index.html','utf8');
const code = html.split('// BEGIN PURE RESULT HELPERS')[1].split('// END PURE RESULT HELPERS')[0];
const context = vm.createContext({});
vm.runInContext(code, context);
const {guidedMessage, resultRows, safeCsv, trendCoordinates} = context;

test('guided questions preserve exact exclusive windows and enforce the month limit', () => {
  assert.equal(guidedMessage('single','orders','2025-01-01','2025-02-01','','','',''), 'metric orders from 2025-01-01 to 2025-02-01');
  assert.equal(guidedMessage('comparison','orders','2025-01-01','2025-02-01','2025-02-01','2025-03-01','',''), 'compare metric orders from 2025-01-01 to 2025-02-01 with from 2025-02-01 to 2025-03-01');
  assert.equal(guidedMessage('trend','orders','','','','','2024-12','2025-02'), 'trend metric orders from 2024-12-01 to 2025-02-01 by month');
  for(const args of [ ['trend','orders','','','','','2024-01','2025-02'], ['trend','orders','','','','','2025-01','2025-01'], ['single','orders','2025-02-29','2025-03-01','','','',''], ['single','orders where active','2025-01-01','2025-02-01','','','',''] ]) assert.throws(()=>guidedMessage(...args));
});

test('exports escape spreadsheet formulas without corrupting decimal values', () => {
  const result={type:'answer',metric:{id:'orders',revision:1,definition:{name:'=danger'}},columns:['region','value'],rows:[['  =HYPERLINK("x")','-12.50'],[null,'0'],['','2']],row_statuses:['value','value','partial_values'],truncated:true,date_scope:{start:'2025-01-01',end_exclusive:'2025-02-01'}};
  const rows=resultRows(result), csv=safeCsv(rows);
  assert.match(csv, /"'=danger"/);
  assert.match(csv, /"'  =HYPERLINK\(""x""\)"/);
  assert.match(csv, /"-12\.50"/);
  assert.equal(rows[2][7], 'true');
  assert.equal(rows[3][7], 'false');
  assert.equal(rows[1][10], true);
  assert.match(csv, /"partial_values"/);
  assert.match(safeCsv([['h'],['\t@danger'],['\n=1']]), /"'\t@danger"/);
});

test('trend and comparison exports retain periods, status and change', () => {
  const metric={id:'sales',revision:2,definition:{name:'Sales'}};
  const scope={start:'2025-01-01',end_exclusive:'2025-02-01'};
  const rows=resultRows({type:'trend',metric,months:[{...scope,value:null,data_status:'missing_values'}]});
  assert.equal(rows[1][3],'2025-01-01');assert.equal(rows[1][8],null);assert.equal(rows[1][9],'missing_values');
  const comparison=resultRows({type:'comparison',metric,baseline:{scope,value:'0',data_status:'value'},current:{scope,value:'5',data_status:'value'},change:{difference:'5',percent_change:null,reason:'zero_baseline'}});
  assert.equal(comparison[2][11],'5');assert.equal(comparison[2][13],'zero_baseline');
  const empty=resultRows({type:'answer',metric,columns:['region','value'],rows:[],row_statuses:[],date_scope:scope});
  assert.equal(empty[1][9],'no_matching_rows');
});

test('trend chart leaves gaps for missing or imprecise values', () => {
  const chart=trendCoordinates([{value:'10',data_status:'value'},{value:null,data_status:'missing_values'},{value:'20',data_status:'value'}]);
  assert.equal(chart.min,10);assert.equal(chart.max,20);assert.equal(chart.points[1],null);
  assert.equal(trendCoordinates([{value:'1234567890123456',data_status:'value'},{value:'1',data_status:'value'}]),null);
});

function mockUi() {
  class Element {
    constructor(tag='div'){this.tagName=tag;this.children=[];this.style={};this.hidden=false;this.value='';this.textContent='';this.firstChild={textContent:''};this.classList={toggle(){}};}
    append(...nodes){this.children.push(...nodes)}
    setAttribute(name,value){this[name]=value}
    focus(){this.focused=true}
    click(){this.clicked=true}
    remove(){this.removed=true}
  }
  const ids={};
  const get=id=>ids[id]||(ids[id]=new Element());
  const document={createElement:tag=>new Element(tag),createElementNS:(ns,tag)=>new Element(tag),body:new Element('body')};
  const ctx=vm.createContext({document,URL:{},Blob:function(){},setTimeout(){},$:get,status(id,message,error=false){get(id).textContent=message;get(id).error=error},option(){},api(){},...context});
  return {ids,get,ctx};
}

test('guided form switches controls and fills chat without sending', () => {
  const {get,ctx}=mockUi();
  const script=html.slice(html.indexOf('function resetGuidedMetrics()'),html.indexOf('function addExport('));
  vm.runInContext(script,ctx);
  get('guidedMetric').value='orders';get('guidedMode').value='trend';
  get('guidedMode').onchange();
  assert.equal(get('guidedStartWrap').hidden,true);assert.equal(get('guidedFirstMonthWrap').hidden,false);
  get('guidedFirstMonth').value='2025-01';get('guidedEndMonth').value='2025-04';get('confirmPlan').hidden=false;
  let prevented=false;get('guidedForm').onsubmit({preventDefault(){prevented=true}});
  assert.equal(prevented,true);assert.equal(get('chatMessage').value,'trend metric orders from 2025-01-01 to 2025-04-01 by month');
  assert.equal(get('confirmPlan').hidden,true);assert.match(get('guidedStatus').textContent,/Send it/);
});

test('trend rendering provides an accessible chart, table and export', () => {
  const {get,ctx}=mockUi();
  const script=html.slice(html.indexOf('function addExport('),html.indexOf('async function loadChats('));
  vm.runInContext(script,ctx);
  const d={type:'trend',metric:{id:'orders',revision:1,definition:{name:'Orders'}},scope:{start:'2025-01-01',end_exclusive:'2025-03-01',filter_note:'No fixed filters apply.'},months:[{start:'2025-01-01',end_exclusive:'2025-02-01',value:'2',data_status:'value'},{start:'2025-02-01',end_exclusive:'2025-03-01',value:'3',data_status:'value'}]};
  ctx.showChatExchange('question',d,false);
  const reply=get('chatLog').children[1];
  const svg=reply.children.find(x=>x.tagName==='svg'),table=reply.children.find(x=>x.tagName==='table'),button=reply.children.find(x=>x.tagName==='button');
  assert.equal(svg.role,'img');assert.match(svg['aria-label'],/Exact values/);assert.equal(table.children.length,3);assert.equal(button.textContent,'Download CSV');
});

test('download action creates a local CSV with protected text', () => {
  const {get,ctx}=mockUi();let downloaded;
  ctx.Blob=function(parts,options){this.parts=parts;this.type=options.type};
  ctx.URL={createObjectURL(blob){downloaded=blob;return 'blob:local'},revokeObjectURL(){}};
  const script=html.slice(html.indexOf('function addExport('),html.indexOf('async function loadChats('));
  vm.runInContext(script,ctx);
  const d={type:'answer',metric:{id:'orders',revision:1,definition:{name:'Orders'}},columns:['region','value'],rows:[['=1+1','2']],row_statuses:['value'],date_scope:{start:'2025-01-01',end_exclusive:'2025-02-01'}};
  ctx.showChatExchange('question',d,false);
  const button=get('chatLog').children[1].children.find(x=>x.tagName==='button');button.onclick();
  assert.equal(downloaded.type,'text/csv;charset=utf-8');assert.match(downloaded.parts[1],/"'=1\+1"/);
  assert.equal(ctx.document.body.children[0].download,'contexta-result.csv');
});
