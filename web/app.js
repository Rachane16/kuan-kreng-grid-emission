"use strict";
const $ = (id) => document.getElementById(id);
const COLORS = {GRASS:"#9aa95a",LEPIRONIA:"#48aaa0",M_CAJU:"#3c7654",PADDY:"#c4ae62",PEAT:"#b2845d"};
const LABELS = {GRASS:["หญ้า","GRASS"],LEPIRONIA:["กระจูด","LEPIRONIA"],M_CAJU:["เสม็ดขาว","MELALEUCA"],
 PADDY:["ข้าว","PADDY / RICE"],PEAT:["ดินพรุ 0–10 cm","PEAT"],
 M_CAJU_SURFACE_LOWLAND:["เชื้อเพลิงผิวดินในป่าเสม็ด","Surface fuel (litter + undergrowth)"],
 M_CAJU_LEAVES_BARK_LOWLAND:["ใบและเปลือกเสม็ดขาว","M. cajuputi leaves + bark"]};
const SOURCE_NAMES={MODIS_NRT:"MODIS Terra / Aqua",VIIRS_SNPP_NRT:"VIIRS S-NPP",VIIRS_NOAA20_NRT:"VIIRS NOAA-20",VIIRS_NOAA21_NRT:"VIIRS NOAA-21",ALL:"ทุกดาวเทียม"};
const state={index:{dates:[],daily:[]},status:{},parameters:null,project:null,day:null,source:"ALL",peat:true,map:null,boundary:null,landuse:{},dailyLayer:null,hotspotLayer:null,gridReference:null,request:0,baseLayers:{},baseLayer:null};
const format=(n,d=2)=>Number.isFinite(n)?new Intl.NumberFormat("en-US",{minimumFractionDigits:0,maximumFractionDigits:d}).format(n):"—";
const safe=(s)=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const today=()=>new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Bangkok",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
const dateText=(s)=>new Intl.DateTimeFormat("th-TH",{timeZone:"Asia/Bangkok",day:"numeric",month:"long",year:"numeric"}).format(new Date(s+"T12:00:00+07:00"));
const clockText=(s)=>s?new Intl.DateTimeFormat("th-TH",{timeZone:"Asia/Bangkok",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(s)):"—";
async function json(path){const r=await fetch(path,{cache:"no-store"});if(!r.ok)throw new Error("ไม่พบข้อมูลที่ต้องการ ("+r.status+")");if(path.endsWith(".gz")){if(!window.DecompressionStream)throw new Error("โปรดใช้เบราว์เซอร์รุ่นใหม่เพื่อเปิดชั้นแผนที่");return new Response(r.body.pipeThrough(new DecompressionStream("gzip"))).json();}return r.json();}
function fuelColor(code){if(code==="M_CAJU_LEAVES_BARK_LOWLAND")return "#83a993";return COLORS[code.startsWith("M_CAJU")?"M_CAJU":code]||"#8da290";}
function fuelName(code){const a=LABELS[code]||[code,""];return '<span class="fuel-label"><i style="background:'+fuelColor(code)+'"></i><span class="fuel-name">'+safe(a[0])+'<small>'+safe(a[1])+'</small></span></span>';}
function emission(summary){return summary?(state.peat?summary.emission_kg:summary.emission_without_peat_kg):null;}
function setMapMessage(title,detail,show=true){$("map-message").hidden=!show;$("map-message").innerHTML='<span class="map-message-icon">⌖</span><strong>'+safe(title)+'</strong><span>'+safe(detail)+'</span>';}
function currentSummary(){
 if(!state.day)return null;
 const result=state.day.by_source[state.source];
 if(state.source!=="ALL" && state.day.source_status[state.source]?.state!=="ok" && !result?.observation_count)return null;
 return result;
}
function renderStatus(){
 const historical=state.day?.collection_mode==="historical";
 const s=historical?{state:state.day.data_state,sources:state.day.source_status,message:"ข้อมูลย้อนหลังของวันที่เลือก · เวลาไทย UTC+7 · ใช้ SP หรือ NRT ตามช่วงข้อมูลที่ NASA มี"}:state.status;
 const title={awaiting_key:"พร้อมแสดงแผนที่ · รอเชื่อม FIRMS MAP_KEY",ok:"อัปเดตข้อมูล FIRMS สำเร็จ",partial:"ข้อมูลดาวเทียมอัปเดตไม่ครบ",error:"การอัปเดตขัดข้อง · ใช้ข้อมูลที่บันทึกไว้"};
 $("connection-title").textContent=historical?("ข้อมูลย้อนหลัง · "+(s.state==="ok"?"ครบทุกแหล่ง":"ข้อมูลบางส่วน")):title[s.state]||"ยังไม่มีข้อมูลเชื่อมต่อ";
 $("connection-detail").textContent=s.state==="awaiting_key"?"ขอบเขตและเชื้อเพลิงเป็นข้อมูลจริงของโครงการ ยังไม่มีข้อมูล Active Fires จาก API":s.message||"";
 $("connection-label").textContent=(historical?"HISTORICAL DATA":{awaiting_key:"AWAITING CONNECTION",ok:"NRT DATA",partial:"PARTIAL DATA",error:"STALE DATA"}[s.state])||"OFFLINE";
 $("connection-banner").classList.toggle("ok",s.state==="ok");
 $("source-status").innerHTML=Object.keys(SOURCE_NAMES).filter(k=>k!=="ALL").map(k=>{
 const q=s.sources?.[k]||{},v=q.state||"not_configured";
 const text={ok:"อัปเดตแล้ว",error:"ขัดข้อง",not_configured:"รอเชื่อมต่อ",unavailable:"ยังไม่มีข้อมูลใหม่"}[v]||v;
 return '<div class="source-item"><i class="source-dot '+safe(v)+'"></i><span>'+SOURCE_NAMES[k]+'</span><span class="source-state">'+safe(historical?({ok:"โหลดแล้ว",partial:"บางช่วงขาดข้อมูล",error:"ขัดข้อง",unavailable:"ไม่มีชุดข้อมูล"}[v]||text):text)+(historical?'<small>'+safe((q.api_products||[]).join(" / "))+'</small>':"")+(q.max_date?'<small>ล่าสุด '+safe(q.max_date)+'</small>':'')+'</span></div>';
 }).join("");
 $("last-update").textContent=historical?"นำเข้าย้อนหลัง "+clockText(state.day.generated_utc)+" น.":s.last_success_utc?"อัปเดตครบทุกแหล่งล่าสุด "+clockText(s.last_success_utc)+" น.":s.last_partial_success_utc?"อัปเดตบางแหล่งล่าสุด "+clockText(s.last_partial_success_utc)+" น.":"ยังไม่มีการอัปเดตจาก FIRMS";
}
function renderParameters(){
 const value=(p,key)=>format(p[key],3)+(p[key+"_plus_minus"]!==undefined?" ± "+format(p[key+"_plus_minus"],3):p[key+"_range"]?" ("+p[key+"_range"].map(v=>format(v,3)).join("–")+")":"");
 $("parameter-table").innerHTML=state.parameters.fuels.map(p=>'<tr><td>'+fuelName(p.code)+'</td><td>'+value(p,"rho")+'</td><td>'+value(p,"eta")+'</td><td>'+value(p,"ef_pm25")+'</td><td class="references">'+safe(p.references||"—")+'</td></tr>').join("");
}
function render(){
 renderStatus();
 const summary=currentSummary(),valid=!!summary;
 $("metric-grids").textContent=valid?format(summary.grid_count,0):"—";
 $("metric-clusters").textContent=valid?format(summary.cluster_count,0):"—";
 $("metric-count").textContent=valid?format(summary.observation_count,0):"—";
 $("metric-area").textContent=valid?format(summary.ground_area_ha):"—";
 $("metric-emission").textContent=valid?format(emission(summary)):"—";
 $("metric-unclassified").textContent=valid?format(summary.surface_unclassified_ha):"—";
 $("emission-unit").textContent="kg · "+(state.peat?"รวมสถานการณ์ดินพรุ":"เฉพาะเชื้อเพลิงเหนือดิน");
 $("selected-day-label").textContent=dateText($("date-input").value)+(state.day?.data_state==="partial"?" · ข้อมูลบางส่วน":"")+($("date-input").value===today()?" · วันปัจจุบันยังไม่ครบวัน":"");
 $("map-subtitle").textContent=SOURCE_NAMES[state.source]+" / "+$("date-input").value+" / เวลาไทย";
 $("export-button").disabled=!valid;
 $("fuel-table").innerHTML=state.parameters.fuels.map(p=>{
 const r=summary?.fuels.find(f=>f.code===p.code),excluded=p.code==="PEAT"&&!state.peat;
 return '<tr class="'+(p.code==="PEAT"?"peat-row ":"")+(excluded?"excluded":"")+'"><td>'+fuelName(p.code)+'</td><td>'+format(r?.area_ha)+'</td><td>'+(excluded?"ไม่รวม":format(r?.emission_kg))+'</td></tr>';
 }).join("");
 $("table-total").textContent=format(emission(summary));
 drawFires();
 renderTrend();
}
function gridPopup(p,kind="cell",point=null){
 const title=kind==="cluster"?"กลุ่มกริด "+p.cluster_id:"กริด "+p.grid_id;
 const rows=p.fuels.filter(r=>r.area_ha>0).map(r=>'<tr class="'+(r.peat_scenario&&!state.peat?"excluded":"")+'"><td>'+safe(LABELS[r.code]?.[0]||r.code)+'</td><td>'+format(r.area_ha,3)+'</td><td>'+(!state.peat&&r.peat_scenario?"ไม่รวม":format(r.emission_kg,3))+'</td></tr>').join("");
 return '<div class="pixel-popup grid-popup"><strong>'+safe(title)+'</strong><div class="pixel-metadata">'+p.grid_count+' กริด · '+p.observation_count+' รายการตรวจพบ<br>'+safe(p.sources.map(s=>SOURCE_NAMES[s]).join(" / "))+'<br>เวลาไทย '+safe(clockText(p.first_acquired_utc))+' – '+safe(clockText(p.last_acquired_utc))+' น.'+(point?'<br>จุดนี้: '+safe(SOURCE_NAMES[point.source])+' · '+safe(clockText(point.acquired_utc))+' น.':"")+'</div><div class="pixel-totals"><span>พื้นที่สมมติเผาเต็มกริด<strong>'+format(p.ground_area_ha,3)+' ha</strong></span><span>PM₂.₅ emission<strong>'+format(state.peat?p.emission_kg:p.emission_without_peat_kg,3)+' kg</strong></span></div><table><thead><tr><th>เชื้อเพลิง</th><th>ha</th><th>PM₂.₅ (kg)</th></tr></thead><tbody>'+rows+'</tbody></table><p class="pixel-note">สมมติฐานเผาเต็มส่วนกริดในขอบเขตศึกษา · รายวันอิสระ<br>'+(state.peat?"รวมสมมติฐานเผาดินพรุ 0–10 cm":"ไม่รวมสถานการณ์ดินพรุ")+'<br>'+(kind==="cell"?"กลุ่ม: "+safe(p.cluster_id):"แต่ละกริดรวมในยอดกลุ่มเพียงครั้งเดียว")+'</p></div>';
}
function drawFires(){
 if(!state.map)return;
 for(const key of ["dailyLayer","hotspotLayer"]){if(state[key]){state.map.removeLayer(state[key]);state[key]=null;}}
 const summary=currentSummary();
 if(!state.day||!summary){
  setMapMessage("ยังไม่มีข้อมูลกริดของวันที่เลือก","เลือกวันที่มีประวัติ หรือให้นำเข้าข้อมูลย้อนหลัง",true);return;
 }
 if(!summary.grid_count){
  setMapMessage("ไม่พบกริดที่มีจุดความร้อนในข้อมูลที่ได้รับ",state.day.data_state==="partial"?"บางแหล่งยังมีข้อมูลไม่ครบ":"ตามวันที่และดาวเทียมที่เลือก",true);return;
 }
 setMapMessage("","",false);
 const kind=$("display-mode").value==="clusters"?"cluster":"cell";
 const features=kind==="cluster"?summary.clusters:summary.cells;
 state.dailyLayer=L.geoJSON(features,{pane:"fire",renderer:L.svg({pane:"fire"}),
  style:{color:kind==="cluster"?"#9d4c1f":"#ce702f",weight:kind==="cluster"?2.5:1.3,fillColor:"#e98c43",fillOpacity:.35},
  onEachFeature:(feature,layer)=>{
   layer.bindPopup(()=>gridPopup(feature.properties,kind),{maxWidth:470,minWidth:300,maxHeight:450});
   layer.on("add",()=>{const el=layer.getElement();if(el){el.setAttribute("role","button");el.setAttribute("tabindex","0");
    el.setAttribute("aria-label",kind==="cluster"?"กลุ่มกริด "+feature.properties.cluster_id:"กริด "+feature.properties.grid_id);
    el.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();layer.openPopup();}});
   }});
  }}).addTo(state.map);
 if($("show-hotspots").checked){
  const cells=new Map(summary.cells.features.map(f=>[f.properties.grid_id,f.properties]));
  const points={type:"FeatureCollection",features:state.day.hotspots.features.filter(f=>state.source==="ALL"||f.properties.source===state.source)};
  const hotspotRenderer=L.svg({pane:"hotspots"});
  state.hotspotLayer=L.geoJSON(points,{pane:"hotspots",
   pointToLayer:(feature,latlng)=>L.circleMarker(latlng,{pane:"hotspots",renderer:hotspotRenderer,radius:3.5,color:"#a33522",weight:1,fillColor:"#f35132",fillOpacity:1}),
   onEachFeature:(feature,layer)=>{const p=cells.get(feature.properties.grid_id);if(p)layer.bindPopup(()=>gridPopup(p,"cell",feature.properties),{maxWidth:470,minWidth:300,maxHeight:450});}
  }).addTo(state.map);
 }
}
async function loadGrid(){
 try{
  const data=await json("data/study_grid.geojson.gz");
  state.gridReference=L.geoJSON(data,{pane:"grid",interactive:false,style:{color:"#778f82",weight:.6,fill:false,opacity:.45}});
  if($("show-grid").checked)state.gridReference.addTo(state.map);
  $("grid-total").textContent=format(data.features.length,0);
 }catch(e){$("grid-total").textContent="โหลดไม่สำเร็จ";}
}
function renderTrend(){
 const source=state.source,last=$("trend-range").value==="custom"?$("trend-end").value:today();
 const first=$("trend-range").value==="custom"?$("trend-start").value:ChartData.shift(last,-Number($("trend-range").value)+1);
 let rows;try{rows=ChartData.series(state.index,first,last,source,state.peat);}
 catch(e){$("trend-summary").textContent=e.message;return;}
 const known=rows.filter(r=>r.value!==null),partial=known.filter(r=>r.state==="partial").length;
 $("trend-subtitle").textContent=SOURCE_NAMES[source]+" · "+first+" ถึง "+last+" · kg";
 $("trend-summary").textContent="รวมค่ารายวันที่มีข้อมูล "+format(known.reduce((s,r)=>s+r.value,0))+" kg · มีข้อมูล "+known.length+"/"+rows.length+" วัน"+(partial?" · ข้อมูลบางส่วน "+partial+" วัน":"");
 const width=Math.max(700,rows.length*23,$("trend").clientWidth-2),height=225,base=175,pad=55,plot=width-pad-12,gap=plot/rows.length;
 const max=Math.max(1,...known.map(r=>r.value));
 let svg='<svg viewBox="0 0 '+width+' '+height+'" style="min-width:'+width+'px" role="img" aria-label="กราฟ PM₂.₅ emission รายวันแยกเชื้อเพลิง">';
 for(let n=0;n<=4;n++){const y=base-n*140/4;svg+='<line x1="'+pad+'" y1="'+y+'" x2="'+width+'" y2="'+y+'" stroke="#e0e8df"/><text x="'+(pad-8)+'" y="'+(y+4)+'" text-anchor="end" fill="#637d72" font-size="11">'+format(max*n/4,max<4?2:0)+'</text>';}
 rows.forEach((r,i)=>{
  const x=pad+i*gap+gap*.15,w=gap*.7,opacity=r.state==="partial"?.5:1;
  svg+='<g tabindex="0" role="button" data-chart-date="'+r.date+'" aria-label="'+r.date+' '+(r.value===null?"ไม่มีข้อมูล":format(r.value)+" kg")+'"><title>'+r.date+': '+(r.value===null?"ไม่มีข้อมูล":format(r.value)+" kg"+(r.state==="partial"?" · ข้อมูลบางส่วน":""))+'</title>';
  svg+='<rect x="'+x+'" y="30" width="'+w+'" height="148" fill="transparent"/>';
  if(r.value===null)svg+='<rect x="'+x+'" y="35" width="'+w+'" height="140" fill="#edf0ed" stroke="#cad3ca" stroke-dasharray="3 3"/>';
  else{
   let y=base;
   const fuelSum=r.fuels.reduce((s,f)=>s+f.emission_kg,0);
   if(r.value>0&&fuelSum>0)r.fuels.forEach(f=>{const h=f.emission_kg/max*140;y-=h;svg+='<rect x="'+x+'" y="'+y+'" width="'+w+'" height="'+h+'" fill="'+fuelColor(f.code)+'" opacity="'+opacity+'"><title>'+r.date+' · '+safe(LABELS[f.code]?.[0]||f.code)+': '+format(f.emission_kg)+' kg</title></rect>';});
   else svg+='<rect x="'+x+'" y="'+(base-2)+'" width="'+w+'" height="2" fill="#4a8a6f" opacity="'+opacity+'"/>';
  }

  if(rows.length<=10||i%5===0||i===rows.length-1)svg+='<text x="'+(x+w/2)+'" y="196" text-anchor="middle" fill="#617b70" font-size="11">'+r.date.slice(5)+'</text>';
  svg+='</g>';
 });
 $("trend").innerHTML=svg+'</svg>';
 const selectDate=day=>{$("date-input").value=day;loadDay();};
 $("trend").querySelectorAll("[data-chart-date]").forEach(e=>{
  e.addEventListener("click",()=>selectDate(e.dataset.chartDate));
  e.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();selectDate(e.dataset.chartDate);}});
 });
 $("trend-legend").innerHTML=state.parameters.fuels.filter(f=>state.peat||f.code!=="PEAT").map(f=>'<span><i style="background:'+fuelColor(f.code)+'"></i>'+safe(LABELS[f.code][0])+'</span>').join("");
 $("date-history").innerHTML=known.slice(-7).map(r=>'<button data-date="'+r.date+'" class="'+(r.date===$("date-input").value?"active":"")+'">'+r.date.slice(5)+'</button>').join("");
 $("date-history").querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>selectDate(b.dataset.date)));
}

async function loadDay(){
 const ticket=++state.request,day=$("date-input").value;
 state.day=null;
 if(state.index.dates.includes(day)){
  try{const data=await json("data/daily/"+day+".json");if(ticket!==state.request)return;if(data.model_id!=="full_grid_1km_v1")throw Error("Model mismatch");state.day=data;}
  catch(e){$("connection-detail").textContent="เปิดข้อมูลรายวันไม่สำเร็จ กรุณาลองโหลดใหม่";}
 }
 if(ticket===state.request)render();
}
async function refresh(){
 $("refresh-button").disabled=true;
 try{
 [state.index,state.status]=await Promise.all([json("data/index.json"),json("data/status.json")]);
 $("archive-coverage").textContent="มีข้อมูลบันทึก "+state.index.dates.length+" วัน · วันที่อื่นต้องนำเข้าย้อนหลัง";
 await loadDay();
 }catch(e){$("connection-title").textContent="โหลดข้อมูลไม่สำเร็จ";$("connection-detail").textContent=e.message;}
 finally{$("refresh-button").disabled=false;}
}
function initializeMap(boundary){
 if(!window.L){setMapMessage("โหลดเครื่องมือแผนที่ไม่สำเร็จ","ไฟล์ Leaflet ไม่พร้อมใช้งาน");return;}
 state.map=L.map("map",{preferCanvas:true,zoomControl:false});
 L.control.zoom({position:"topright"}).addTo(state.map);
 L.control.scale({imperial:false,position:"bottomright"}).addTo(state.map);
 state.map.createPane("grid");state.map.getPane("grid").style.zIndex=415;
 state.map.createPane("hotspots");state.map.getPane("hotspots").style.zIndex=470;
 state.map.createPane("landuse");state.map.getPane("landuse").style.zIndex=410;
 state.map.createPane("fire");state.map.getPane("fire").style.zIndex=440;
 state.map.createPane("boundary");state.map.getPane("boundary").style.zIndex=450;state.map.getPane("boundary").style.pointerEvents="none";
 const esri='Sources: Esri, HERE, Garmin, Intermap, increment P Corp., GEBCO, USGS, FAO, NPS, NRCAN, GeoBase, IGN, Kadaster NL, Ordnance Survey, Esri Japan, METI, Esri China (Hong Kong), © OpenStreetMap contributors, and the GIS User Community';
 state.baseLayers={
  osm:L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',maxZoom:19}),
  imagery:L.tileLayer("https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",{attribution:"Tiles © Esri — Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community",maxZoom:19}),
  topo:L.tileLayer("https://services.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",{attribution:esri,maxZoom:19})
 };
 state.baseLayer=state.baseLayers.osm;state.baseLayer.addTo(state.map);
 $("basemap-select").addEventListener("change",e=>{if(state.baseLayer)state.map.removeLayer(state.baseLayer);state.map.getContainer().dataset.basemap=e.target.value;state.baseLayer=state.baseLayers[e.target.value];state.baseLayer.addTo(state.map);});
 
 state.boundary=L.geoJSON(boundary,{pane:"boundary",style:{color:"#285b4b",weight:1.7,dashArray:"6 5",fill:false}}).addTo(state.map);
 state.map.fitBounds(state.boundary.getBounds(),{padding:[25,25]});
 drawFires();
}
async function loadLanduse(){
 try{
 const data=await json("data/landuse_layers.geojson.gz");
 if(!state.map)return;
 data.features.forEach(f=>{
  const code=f.properties.landuse_code;
  state.landuse[code]=L.geoJSON(f,{pane:"landuse",style:{color:COLORS[code],weight:.4,opacity:.7,fillColor:COLORS[code],fillOpacity:code==="PEAT"?.2:.32},
  onEachFeature:(feature,layer)=>layer.bindPopup("<strong>"+safe(LABELS[code][0])+"</strong><br>พื้นที่ในขอบเขต: "+format(feature.properties.area_ha)+" ha")});
  if($("layer-"+code).checked)state.landuse[code].addTo(state.map);
 });
 $("layer-load-status").textContent="Landuse 5 ชั้น · ข้อมูลพื้นที่จริง";
 }catch(e){$("layer-load-status").textContent="โหลด Landuse ไม่สำเร็จ · ลองโหลดหน้าใหม่";$("layer-load-status").classList.add("error-message");}
}
function exportCsv(){
 const summary=currentSummary();if(!summary)return;
 const header=["date_thailand","source","fuel","area_ha","rho_tonne_dm_ha","eta","ef_g_kg","emission_kg","included_in_total"];
 const rows=summary.fuels.map(r=>[$("date-input").value,state.source,r.code,r.area_ha,r.rho,r.eta,r.ef_pm25,r.emission_kg,!r.peat_scenario||state.peat]);
 const csv=[header,...rows].map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(",")).join("\r\n");
 const blob=new Blob(["\ufeff"+csv],{type:"text/csv;charset=utf-8"});
 const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="kk-psf-grid-emission-"+$("date-input").value+"-"+state.source+".csv";a.click();URL.revokeObjectURL(url);
}
async function init(){
 $("date-input").value=today();$("date-input").max=today();
 const requestedDate=new URLSearchParams(location.search).get("date");
 if(requestedDate&&/^\d{4}-\d{2}-\d{2}$/.test(requestedDate)&&requestedDate<=today())$("date-input").value=requestedDate;
 $("layer-controls").innerHTML=Object.keys(COLORS).map(code=>'<label><input type="checkbox" id="layer-'+code+'" '+(code!=="PEAT"?"checked":"")+'><span>'+LABELS[code][0]+'</span><i class="layer-color" style="background:'+COLORS[code]+'"></i></label>').join("");
 Object.keys(COLORS).forEach(code=>$("layer-"+code).addEventListener("change",e=>{const layer=state.landuse[code];if(layer&&state.map){if(e.target.checked)layer.addTo(state.map);else state.map.removeLayer(layer);}}));
 $("date-input").addEventListener("change",()=>{if($("date-input").value)loadDay();});
 $("sensor-select").addEventListener("change",e=>{state.source=e.target.value;render();});
 $("include-peat").addEventListener("change",e=>{state.peat=e.target.checked;render();});
 $("trend-start").value=ChartData.shift(today(),-6);$("trend-end").value=today();
 $("trend-start").max=today();$("trend-end").max=today();
 $("trend-range").addEventListener("change",()=>{$("trend-custom").hidden=$("trend-range").value!=="custom";renderTrend();});
 $("trend-apply").addEventListener("click",renderTrend);
 window.addEventListener("resize",()=>{if(state.parameters)renderTrend();});

 $("refresh-button").addEventListener("click",refresh);
 $("export-button").addEventListener("click",exportCsv);
 $("display-mode").addEventListener("change",drawFires);$("show-hotspots").addEventListener("change",drawFires);
 $("show-grid").addEventListener("change",e=>{if(state.gridReference){if(e.target.checked)state.gridReference.addTo(state.map);else state.map.removeLayer(state.gridReference);}});
 $("fit-map").addEventListener("click",()=>{if(state.map&&state.boundary)state.map.fitBounds(state.boundary.getBounds(),{padding:[25,25]});});
 for(const [button,dialog] of [["parameters-button","parameters-dialog"],["method-button","method-dialog"]])$(button).addEventListener("click",()=>$(dialog).showModal());
 document.querySelectorAll("[data-close]").forEach(b=>b.addEventListener("click",()=>$(b.dataset.close).close()));
 for(const [id,offset] of [["prev-day",-1],["next-day",1]])$(id).addEventListener("click",()=>{
  const d=new Date($("date-input").value+"T12:00:00Z");d.setUTCDate(d.getUTCDate()+offset);const value=d.toISOString().slice(0,10);if(value<=today()){$("date-input").value=value;loadDay();}
 });
 try{
 const [project,parameters,boundary]=await Promise.all([json("data/project.json"),json("data/parameters.json"),json("data/study_area.geojson")]);
 state.project=project;state.parameters=parameters;
 $("study-area").innerHTML=format(project.study_area_ha,0)+" <small>ha</small>";
 renderParameters();initializeMap(boundary);await refresh();loadLanduse();loadGrid();
 }catch(e){$("connection-title").textContent="ข้อมูลโครงการยังไม่พร้อม";$("connection-detail").textContent=e.message;setMapMessage("เปิดข้อมูลโครงการไม่สำเร็จ","ตรวจการเตรียมไฟล์และการเชื่อมต่อ");}
}
init();
