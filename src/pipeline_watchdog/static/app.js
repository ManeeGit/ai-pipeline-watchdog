'use strict';
let state = null;
let inFlight = false;
let selectedIncident = null;
const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; };
const fmt = value => Number(value).toLocaleString();
const date = value => value ? new Date(value).toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : 'Not observed';
function spark(history, severity) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 260 53'); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('class', 'sparkline'); svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Row volume over the latest observations');
  if (!history.length) return svg;
  const values = history.map(h => h.row_count); const max = Math.max(...values, 1); const min = Math.min(...values, 0);
  const points = values.map((v,i) => [i * 260 / Math.max(values.length-1,1), 46 - (v-min)/(max-min)*38]);
  const polygon = document.createElementNS(svg.namespaceURI,'polygon');
  polygon.setAttribute('points', `0,53 ${points.map(p=>p.join(',')).join(' ')} 260,53`);
  polygon.setAttribute('fill', severity === 'healthy' ? '#6fd6b00e' : '#f2bd720d');
  const path = document.createElementNS(svg.namespaceURI,'polyline'); path.setAttribute('points', points.map(p=>p.join(',')).join(' ')); path.setAttribute('fill','none'); path.setAttribute('stroke', severity === 'critical' ? '#f18484' : severity === 'warning' ? '#f2bd72' : '#6fd6b0'); path.setAttribute('stroke-width','1.7');
  svg.append(polygon,path); return svg;
}
function book(item) {
  const details=el('details'); const title=el('summary',null,item.title); const steps=el('ol'); item.steps.forEach(step=>steps.append(el('li',null,step))); details.append(title,steps); return details;
}
function drawIncidents() {
  const filter=$('filter').value; const items=state.incidents.filter(i=>filter==='all'||i.status===filter); const list=$('incident-list'); list.replaceChildren(); $('inbox-count').textContent=items.length;
  if(!items.length) list.append(el('div','empty',filter==='resolved'?'No resolved incidents yet.':'No incidents in this view.'));
  items.forEach(item=>{ const button=el('button','incident'); button.type='button'; const row=el('div','incident-row'); row.append(el('h3',null,item.title),el('span',`badge ${item.status==='resolved'?'healthy':item.severity}`,item.status==='resolved'?'resolved':item.severity));
    const meta=el('p'); meta.append(el('code',null,item.pipeline),document.createTextNode(` · ${item.check.replaceAll('_',' ')} · observed ${item.occurrences}×`)); button.append(row,meta); button.addEventListener('click',()=>openIncident(item)); list.append(button); });
}
function fillDetail(item) {
  $('detail-title').textContent=item.title; $('detail-meta').textContent=`${item.pipeline} · ${item.status} · First seen ${date(item.first_seen)} · Evidence snapshot #${item.snapshot_id}`;
  $('detail-evidence').textContent=JSON.stringify({incident_id:item.id,...item.evidence},null,2); $('detail-runbook').replaceChildren();
  const rb=state.triage.recommended_runbooks.find(r=>r.id===item.runbook); if(rb){const b=book(rb); b.open=true; $('detail-runbook').append(b);}
}
function openIncident(item) { selectedIncident=item.id; fillDetail(item); if(!$('detail').open) $('detail').showModal(); }
function render(data) {
  state=data; $('deployment-mode').textContent=data.deployment?'GCP · IAM':'LOCAL-FIRST'; const open=data.incidents.filter(i=>i.status==='open'); const healthy=data.pipelines.filter(p=>p.snapshot&&p.snapshot.healthy).length;
  $('pipeline-count').textContent=data.pipelines.length; $('healthy-count').textContent=`${healthy}/${data.pipelines.length}`; $('healthy-note').textContent=healthy===data.pipelines.length?'All observed checks passing':'Review affected stages below';
  $('incident-count').textContent=open.length; $('incident-note').textContent=`${open.filter(i=>i.severity==='critical').length} critical · ${open.filter(i=>i.severity==='warning').length} warning`;
  const scan=data.stats.last_scan; $('scan-latency').textContent=scan?`${Math.round(scan.duration_ms)} ms`:'–'; $('scan-note').textContent=`${fmt(data.stats.scan_count)} scans persisted locally`; $('last-scan').textContent=scan?`Last scan ${date(scan.observed_at)}`:'No scans yet';
  const age=scan?(Date.now()-new Date(scan.observed_at).getTime())/60000:Infinity;
  const staleMinutes=(data.deployment?.max_scan_age_seconds??300)/60;
  $('connection-label').textContent=age>staleMinutes?'Dashboard connected · scan overdue':'Dashboard connected'; $('connection').className=`status-dot ${age>staleMinutes?'warn':'good'}`;
  $('pipelines').replaceChildren();
  data.pipelines.forEach(p=>{ const current=open.filter(i=>i.pipeline===p.name); const severity=!p.snapshot?'unknown':current.some(i=>i.severity==='critical')?'critical':current.length?'warning':'healthy'; const card=el('article','pipeline');
    const top=el('div','pipeline-top'); top.append(el('span','pipeline-name',p.name),el('span',`badge ${severity}`,severity)); card.append(top,el('div','pipeline-deps',p.dependencies.length?`Depends on ${p.dependencies.join(', ')}`:'Source · no upstream dependencies'));
    const stats=el('div','pipeline-stats'); const rows=el('div',null); rows.append(el('b',null,p.snapshot?fmt(p.snapshot.row_count):'–'),document.createTextNode('ROWS OBSERVED')); const lag=el('div',null); lag.append(el('b',null,p.snapshot&&p.snapshot.freshness_minutes!==null?`${Math.round(p.snapshot.freshness_minutes)}m`:'–'),document.createTextNode(`FRESHNESS / ${p.max_age_minutes}m SLO`)); stats.append(rows,lag); card.append(stats,spark(p.history,severity)); $('pipelines').append(card); });
  drawIncidents(); $('triage-summary').textContent=data.triage.summary; $('candidates').replaceChildren();
  data.triage.root_candidates.forEach(c=>{const card=el('div','candidate');card.append(el('b',null,c.candidate_pipeline),el('p',null,`Affected chain: ${c.affected_pipelines.join(' → ')}`),el('small',null,`${c.confidence.toUpperCase()} CONFIDENCE · ${c.evidence_ids.length} supporting incident(s)`));$('candidates').append(card);});
  $('runbooks').replaceChildren(...data.triage.recommended_runbooks.map(book)); $('events').replaceChildren();
  if(!data.stats.events.length) $('events').append(el('div','empty','No incident transitions recorded.'));
  data.stats.events.slice(0,8).forEach(e=>{const item=data.incidents.find(i=>i.id===e.incident_id); const row=el('div','event');const t=el('time',null,date(e.observed_at));t.dateTime=e.observed_at;row.append(t,el('span',`event-type ${e.event}`,e.event),el('code',null,item?`${item.pipeline} / ${item.check}`:e.incident_id));$('events').append(row);});
  if($('detail').open&&selectedIncident){const item=data.incidents.find(i=>i.id===selectedIncident);if(item) fillDetail(item);}
}
async function refresh() {
  if(inFlight) return; inFlight=true; $('refresh').disabled=true;
  try {const response=await fetch('/api/summary',{cache:'no-store',signal:AbortSignal.timeout(10000)});if(!response.ok)throw new Error('Local service returned an error');render(await response.json());$('error').hidden=true;}
  catch(error){$('error').hidden=false;$('error').textContent='Cannot read the local watchdog. Displayed data may be stale. Check the monitoring process and refresh.';$('connection-label').textContent='Disconnected';$('connection').className='status-dot bad';}
  finally{inFlight=false;$('refresh').disabled=false;}
}
$('filter').addEventListener('change',()=>{if(state)drawIncidents();});$('refresh').addEventListener('click',refresh);$('close-detail').addEventListener('click',()=>$('detail').close());$('detail').addEventListener('close',()=>{selectedIncident=null;});
$('detail').addEventListener('click',event=>{if(event.target===$('detail')){const r=$('detail').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('detail').close();}});
refresh(); setInterval(()=>{if(!document.hidden)refresh();},5000);
