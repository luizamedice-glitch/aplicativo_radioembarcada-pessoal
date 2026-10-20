const $=id=>document.getElementById(id);
const fmt=n=>new Intl.NumberFormat('pt-BR').format(Number(n||0));
const bytes=n=>{n=Number(n||0);if(n<1024)return n+' B';if(n<1048576)return (n/1024).toFixed(1)+' KB';if(n<1073741824)return (n/1048576).toFixed(1)+' MB';return (n/1073741824).toFixed(2)+' GB'};
async function refresh(){
  try{
    const r=await fetch('/api/stats',{cache:'no-store'});if(!r.ok)throw new Error();
    const d=await r.json();
    $('estimated').textContent=fmt(d.estimated_now);
    $('requests5m').textContent=fmt(d.segment_requests_5m);
    $('requestsToday').textContent=fmt(d.requests_today);
    $('downloadToday').textContent=bytes(d.download_bytes_today);
    $('daily').innerHTML=(d.daily||[]).map(x=>'<tr><td>'+x.date+'</td><td>'+fmt(x.requests)+'</td></tr>').join('')||'<tr><td colspan="2">Sem dados</td></tr>';
    $('status').textContent='R2 · '+(d.updated_at||'');
    $('error').classList.remove('show');
  }catch{
    $('error').textContent='Não foi possível carregar os dados do R2.';
    $('error').classList.add('show');$('status').textContent='Sem dados';
  }
}
refresh();setInterval(refresh,30000);
