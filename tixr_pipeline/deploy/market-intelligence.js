// ── Market Intelligence Tab ──
// World Bank data embedded
var WB_DATA = {
  "Japan":{gdp:33836,internet:87.0,mobile:178.4,tourism:4115799,r:"APAC"},
  "Australia":{gdp:65058,internet:97.1,mobile:112.5,tourism:1828000,r:"APAC"},
  "Germany":{gdp:54777,internet:92.5,mobile:124.7,tourism:12449000,r:"EMEA"},
  "Netherlands":{gdp:63516,internet:97.0,mobile:117.4,tourism:7265000,r:"EMEA"},
  "Spain":{gdp:33493,internet:95.4,mobile:127.7,tourism:36410000,r:"EMEA"},
  "France":{gdp:44700,internet:86.8,mobile:116.7,tourism:117109000,r:"EMEA"},
  "Italy":{gdp:39277,internet:87.0,mobile:131.9,tourism:38419000,r:"EMEA"},
  "United Arab Emirates":{gdp:49851,internet:100.0,mobile:199.4,tourism:8084000,r:"EMEA_Gulf"},
  "Saudi Arabia":{gdp:36157,internet:100.0,mobile:157.8,tourism:20292000,r:"EMEA_Gulf"},
  "Argentina":{gdp:14262,internet:89.2,mobile:137.7,tourism:7399000,r:"LATAM"},
  "Mexico":{gdp:13861,internet:81.2,mobile:111.6,tourism:51128000,r:"LATAM"},
  "Brazil":{gdp:10378,internet:84.2,mobile:101.0,tourism:6353000,r:"LATAM"},
  "Colombia":{gdp:7001,internet:77.3,mobile:167.0,tourism:1396000,r:"LATAM"},
  "Indonesia":{gdp:4876,internet:69.2,mobile:125.2,tourism:4053000,r:"SEA"},
  "Singapore":{gdp:85412,internet:94.3,mobile:173.2,tourism:2742000,r:"SEA"},
  "Malaysia":{gdp:11386,internet:97.7,mobile:142.7,tourism:4333000,r:"SEA"},
  "Philippines":{gdp:3804,internet:83.8,mobile:117.3,tourism:1483000,r:"SEA"},
  "Thailand":{gdp:7195,internet:89.5,mobile:168.6,tourism:39916000,r:"SEA"},
  "Norway":{gdp:82000,internet:98.0,mobile:108.0,tourism:3800000,r:"EMEA"},
  "Sweden":{gdp:56000,internet:97.0,mobile:127.0,tourism:7200000,r:"EMEA"},
  "Denmark":{gdp:68000,internet:98.0,mobile:122.0,tourism:5600000,r:"EMEA"},
  "Switzerland":{gdp:93000,internet:96.0,mobile:130.0,tourism:3900000,r:"EMEA"},
  "Belgium":{gdp:51000,internet:93.0,mobile:98.0,tourism:4100000,r:"EMEA"},
  "Austria":{gdp:53000,internet:93.0,mobile:121.0,tourism:15000000,r:"EMEA"},
  "Finland":{gdp:53000,internet:96.0,mobile:132.0,tourism:3200000,r:"EMEA"},
  "Ireland":{gdp:100000,internet:92.0,mobile:104.0,tourism:4500000,r:"EMEA"},
  "Portugal":{gdp:25000,internet:85.0,mobile:117.0,tourism:17000000,r:"EMEA"},
  "Czech Republic":{gdp:27000,internet:83.0,mobile:122.0,tourism:6500000,r:"EMEA"},
  "Greece":{gdp:20000,internet:82.0,mobile:116.0,tourism:7700000,r:"EMEA"},
  "Poland":{gdp:18000,internet:85.0,mobile:131.0,tourism:5000000,r:"EMEA"},
  "Turkey":{gdp:10000,internet:83.0,mobile:93.0,tourism:24700000,r:"EMEA"},
  "Israel":{gdp:52000,internet:90.0,mobile:135.0,tourism:2700000,r:"EMEA_Gulf"},
  "Qatar":{gdp:83000,internet:99.0,mobile:152.0,tourism:2500000,r:"EMEA_Gulf"},
  "South Korea":{gdp:33000,internet:97.0,mobile:137.0,tourism:4700000,r:"APAC"},
  "New Zealand":{gdp:48000,internet:95.0,mobile:133.0,tourism:1500000,r:"APAC"},
  "India":{gdp:2500,internet:47.0,mobile:83.0,tourism:6000000,r:"APAC"}
};

var miCharts = {};
var regColors = {
  EMEA:'#F0A500',APAC:'#38BDF8',LATAM:'#10B981',SEA:'#A78BFA',
  EMEA_Gulf:'#FB923C',EMEA_Africa:'#EF4444'
};
var chartPalette = [
  '#F0A500','#38BDF8','#10B981','#A78BFA','#FB923C','#F472B6',
  '#22D3EE','#FBBF24','#818CF8','#34D399','#F87171','#E879F9',
  '#2DD4BF','#FCD34D','#93C5FD','#86EFAC','#FCA5A5','#D8B4FE'
];

function fmtK(n){if(n>=1e9)return(n/1e9).toFixed(1)+'B';if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return n.toString();}
function fmtUSD(n){return '$'+n.toLocaleString();}

function getMICountries(region){
  var keys = Object.keys(MKT);
  if(region) keys = keys.filter(function(k){return MKT[k].r === region;});
  return keys.sort(function(a,b){return (MKT[b].n||0)-(MKT[a].n||0);});
}

function renderMI(){
  var rg = document.getElementById('mi-region').value;
  var metric = document.getElementById('mi-metric').value;
  var countries = getMICountries(rg);
  document.getElementById('mi-count').textContent = countries.length + ' markets analyzed';

  // Compute aggregate stats
  var totalVenues=0, totalT1=0, totalT2=0, totalCap=0, sumScore=0, cnt=0;
  var totalGDP=0, gdpCnt=0, totalInternet=0, intCnt=0, totalTourism=0;
  countries.forEach(function(co){
    var m=MKT[co];
    totalVenues+=m.n; totalT1+=m.t1; totalT2+=m.t2;
    sumScore+=m.rs*m.n; cnt+=m.n;
    if(WB_DATA[co]){totalGDP+=WB_DATA[co].gdp; gdpCnt++; totalInternet+=WB_DATA[co].internet; intCnt++; totalTourism+=WB_DATA[co].tourism;}
  });

  // Hero cards
  var heroH='<div class="mi-hero">';
  heroH+='<div class="mi-hero-card gold"><div class="mi-hv" style="color:#F0A500;">'+countries.length+'</div><div class="mi-hl">Markets</div></div>';
  heroH+='<div class="mi-hero-card green"><div class="mi-hv" style="color:#10B981;">'+fmtK(totalVenues)+'</div><div class="mi-hl">Total Venues</div></div>';
  heroH+='<div class="mi-hero-card blue"><div class="mi-hv" style="color:#38BDF8;">'+totalT1+'</div><div class="mi-hl">Tier 1 Venues</div></div>';
  heroH+='<div class="mi-hero-card purple"><div class="mi-hv" style="color:#A78BFA;">'+fmtK(totalT1+totalT2)+'</div><div class="mi-hl">Tier 1+2 Pipeline</div></div>';
  heroH+='<div class="mi-hero-card pink"><div class="mi-hv" style="color:#F472B6;">'+(cnt?((sumScore/cnt).toFixed(1)):'--')+'</div><div class="mi-hl">Avg Rec Score</div></div>';
  heroH+='<div class="mi-hero-card cyan"><div class="mi-hv" style="color:#22D3EE;">'+(gdpCnt?fmtUSD(Math.round(totalGDP/gdpCnt)):'--')+'</div><div class="mi-hl">Avg GDP/Capita</div></div>';
  heroH+='</div>';
  document.getElementById('mi-hero-bar').innerHTML=heroH;

  // ── Chart 1: GDP/Venue/Tourism bar chart (top 15) ──
  var top = countries.slice(0,15);
  var labels = top.map(function(c){return c.length>14?c.substring(0,12)+'..':c;});
  var metricData, metricLabel, metricColor;
  if(metric==='gdp'){metricLabel='GDP per Capita (USD)';metricColor='rgba(240,165,0,0.8)';metricData=top.map(function(c){return WB_DATA[c]?WB_DATA[c].gdp:0;});}
  else if(metric==='internet'){metricLabel='Internet Users (%)';metricColor='rgba(56,189,248,0.8)';metricData=top.map(function(c){return WB_DATA[c]?WB_DATA[c].internet:0;});}
  else if(metric==='mobile'){metricLabel='Mobile Subs per 100';metricColor='rgba(167,139,250,0.8)';metricData=top.map(function(c){return WB_DATA[c]?WB_DATA[c].mobile:0;});}
  else if(metric==='tourism'){metricLabel='International Tourism Arrivals';metricColor='rgba(244,114,182,0.8)';metricData=top.map(function(c){return WB_DATA[c]?WB_DATA[c].tourism:0;});}
  else{metricLabel='Venue Count';metricColor='rgba(16,185,129,0.8)';metricData=top.map(function(c){return MKT[c]?MKT[c].n:0;});}

  if(miCharts.gdp)miCharts.gdp.destroy();
  miCharts.gdp=new Chart(document.getElementById('mi-chart-gdp'),{
    type:'bar',
    data:{labels:labels,datasets:[{label:metricLabel,data:metricData,backgroundColor:top.map(function(c,i){return chartPalette[i%chartPalette.length];}),borderRadius:4,borderSkipped:false}]},
    options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',plugins:{legend:{display:false},title:{display:true,text:metricLabel+' by Country',color:'#9CA3AF',font:{size:12,weight:600}}},scales:{x:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#4B5563',font:{size:10}}},y:{grid:{display:false},ticks:{color:'#9CA3AF',font:{size:10}}}}}
  });
  document.getElementById('mi-chart-gdp').parentElement.style.height='360px';

  // ── Chart 2: Venue Distribution by Region (doughnut) ──
  var regAgg={};
  countries.forEach(function(co){var m=MKT[co];var r=m.r;if(!regAgg[r])regAgg[r]={n:0,t1:0,t2:0};regAgg[r].n+=m.n;regAgg[r].t1+=m.t1;regAgg[r].t2+=m.t2;});
  var regKeys=Object.keys(regAgg).sort(function(a,b){return regAgg[b].n-regAgg[a].n;});
  if(miCharts.venue)miCharts.venue.destroy();
  miCharts.venue=new Chart(document.getElementById('mi-chart-venue'),{
    type:'doughnut',
    data:{labels:regKeys,datasets:[{data:regKeys.map(function(r){return regAgg[r].n;}),backgroundColor:regKeys.map(function(r){return regColors[r]||'#6B7280';}),borderWidth:0,hoverOffset:8}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'65%',plugins:{legend:{position:'bottom',labels:{color:'#9CA3AF',padding:12,font:{size:10},usePointStyle:true,pointStyleWidth:8}},title:{display:true,text:'Venue Distribution by Region',color:'#9CA3AF',font:{size:12,weight:600}}}}
  });
  document.getElementById('mi-chart-venue').parentElement.style.height='340px';

  // ── Chart 3: Tier distribution stacked bar ──
  var topByTier = countries.filter(function(c){return MKT[c].n>=20;}).slice(0,12);
  if(miCharts.tier)miCharts.tier.destroy();
  miCharts.tier=new Chart(document.getElementById('mi-chart-tier'),{
    type:'bar',
    data:{labels:topByTier.map(function(c){return c.length>12?c.substring(0,10)+'..':c;}),datasets:[
      {label:'Tier 1',data:topByTier.map(function(c){return MKT[c].t1;}),backgroundColor:'rgba(16,185,129,0.8)',borderRadius:2},
      {label:'Tier 2',data:topByTier.map(function(c){return MKT[c].t2;}),backgroundColor:'rgba(240,165,0,0.7)',borderRadius:2},
      {label:'Tier 3+',data:topByTier.map(function(c){var m=MKT[c];return Math.max(0,m.n-m.t1-m.t2);}),backgroundColor:'rgba(107,114,128,0.4)',borderRadius:2}
    ]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{color:'#9CA3AF',font:{size:10},usePointStyle:true,pointStyleWidth:8}},title:{display:true,text:'Venue Tier Breakdown by Country',color:'#9CA3AF',font:{size:12,weight:600}}},scales:{x:{stacked:true,grid:{display:false},ticks:{color:'#9CA3AF',font:{size:10}}},y:{stacked:true,grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#4B5563',font:{size:10}}}}}
  });
  document.getElementById('mi-chart-tier').parentElement.style.height='340px';

  // ── Chart 4: Digital Readiness scatter ──
  var scatterData = countries.filter(function(c){return WB_DATA[c]&&MKT[c];}).map(function(c){
    return {x:WB_DATA[c].internet,y:MKT[c].rs,r:Math.max(4,Math.sqrt(MKT[c].n)*1.5),label:c};
  });
  if(miCharts.digital)miCharts.digital.destroy();
  miCharts.digital=new Chart(document.getElementById('mi-chart-digital'),{
    type:'bubble',
    data:{datasets:[{label:'Markets',data:scatterData,backgroundColor:'rgba(56,189,248,0.35)',borderColor:'rgba(56,189,248,0.7)',borderWidth:1}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},title:{display:true,text:'Digital Readiness vs Venue Score (bubble = venue count)',color:'#9CA3AF',font:{size:12,weight:600}},tooltip:{callbacks:{label:function(ctx){var d=ctx.raw;return d.label+': '+d.x+'% internet, Score '+d.y.toFixed(1);}}}},scales:{x:{title:{display:true,text:'Internet Penetration %',color:'#4B5563',font:{size:10}},grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#4B5563',font:{size:10}},min:40,max:105},y:{title:{display:true,text:'Avg Recommendation Score',color:'#4B5563',font:{size:10}},grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#4B5563',font:{size:10}}}}}
  });
  document.getElementById('mi-chart-digital').parentElement.style.height='340px';

  // ── Table ──
  var sortedCountries = countries.slice().sort(function(a,b){
    var am=MKT[a],bm=MKT[b];
    return (bm.rs||0)-(am.rs||0);
  });
  var tbody = document.getElementById('mi-tbody');
  tbody.innerHTML = sortedCountries.map(function(co){
    var m=MKT[co], wb=WB_DATA[co]||{};
    var rc=regColors[m.r]||'#6B7280';
    var sc=m.rs>=65?'#10B981':m.rs>=60?'#F0A500':'#4B5563';
    return '<tr onclick="goCountry(\''+co.replace(/'/g,"\\'")+'\')">' +
      '<td style="font-weight:600;color:#E2E8F0;">'+co+'</td>' +
      '<td><span class="mi-pill" style="background:'+rc+'22;color:'+rc+';border:1px solid '+rc+'44;">'+m.r+'</span></td>' +
      '<td style="font-family:\'Courier New\',monospace;color:#E2E8F0;">'+m.n.toLocaleString()+'</td>' +
      '<td style="color:#10B981;font-family:\'Courier New\',monospace;">'+m.t1+'</td>' +
      '<td style="color:#F0A500;font-family:\'Courier New\',monospace;">'+m.t2+'</td>' +
      '<td><span style="color:'+sc+';font-weight:700;font-family:\'Courier New\',monospace;">'+m.rs.toFixed(1)+'</span></td>' +
      '<td style="color:#9CA3AF;font-family:\'Courier New\',monospace;">'+(wb.gdp?'$'+wb.gdp.toLocaleString():'—')+'</td>' +
      '<td>'+(wb.internet?'<div class="mi-bar-wrap"><div class="mi-bar-track"><div class="mi-bar-fill" style="width:'+wb.internet+'%;background:#38BDF8;"></div></div><span style="font-size:11px;color:#38BDF8;font-family:\'Courier New\',monospace;">'+wb.internet+'%</span></div>':'—')+'</td>' +
      '<td style="color:#A78BFA;font-family:\'Courier New\',monospace;">'+(wb.mobile||'—')+'</td>' +
      '<td style="color:#F472B6;font-family:\'Courier New\',monospace;">'+(wb.tourism?fmtK(wb.tourism):'—')+'</td>' +
      '<td style="font-weight:700;color:'+(m.ms>=50?'#10B981':m.ms>=40?'#F0A500':'#4B5563')+';font-family:\'Courier New\',monospace;">'+(m.ms?m.ms.toFixed(1):'—')+'</td>' +
      '</tr>';
  }).join('');
}

// Extend init to populate MI region filter
(function(){
  var el=document.getElementById('mi-region');
  if(!el)return;
  var regions=Object.keys(REG).sort();
  el.innerHTML='<option value="">All Regions</option>'+regions.map(function(r){return '<option value="'+r+'">'+r+'</option>';}).join('');
})();
