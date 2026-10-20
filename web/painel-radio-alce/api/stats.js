const GRAPHQL='https://api.cloudflare.com/client/v4/graphql';

function iso(d){return d.toISOString();}
function readAction(name){return /(get|read|head)/i.test(String(name||''));}
function requestSum(groups){return (groups||[]).filter(x=>readAction(x?.dimensions?.actionType)).reduce((n,x)=>n+Number(x?.sum?.requests||0),0);}
function segmentReads(groups,prefix){
  return (groups||[]).filter(x=>{
    const name=String(x?.dimensions?.objectName||'');
    return readAction(x?.dimensions?.actionType) && name.endsWith('.ts') && (!prefix || name.startsWith(prefix+'/'));
  }).reduce((n,x)=>n+Number(x?.sum?.requests||0),0);
}
async function gql(token,query,variables){
  const r=await fetch(GRAPHQL,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({query,variables})});
  const body=await r.json().catch(()=>({}));
  if(!r.ok||body.errors) throw new Error('cloudflare_graphql');
  return body.data;
}
export default async function handler(req,res){
  const token=process.env.CLOUDFLARE_ANALYTICS_TOKEN;
  const accountTag=process.env.CLOUDFLARE_ACCOUNT_ID;
  const bucketName=process.env.CLOUDFLARE_R2_BUCKET;
  const prefix=process.env.CLOUDFLARE_R2_PREFIX||'alce-test';
  if(!token||!accountTag||!bucketName) return res.status(503).json({error:'r2_analytics_not_configured'});

  const now=new Date();
  const five=new Date(now.getTime()-5*60*1000);
  const startToday=new Date(now); startToday.setHours(0,0,0,0);
  const days=[];
  for(let i=6;i>=0;i--){const s=new Date(startToday);s.setDate(s.getDate()-i);const e=new Date(s);e.setDate(e.getDate()+1);days.push({s,e});}

  const detailQuery=`query R2Detail($accountTag: string!, $bucketName: string!, $startDate: Time!, $endDate: Time!){
    viewer{accounts(filter:{accountTag:$accountTag}){r2OperationsAdaptiveGroups(limit:10000,filter:{datetime_geq:$startDate,datetime_leq:$endDate,bucketName:$bucketName}){
      sum{requests} dimensions{actionType objectName}
    }}}
  }`;
  const summaryQuery=`query R2Summary($accountTag: string!, $bucketName: string!, $startDate: Time!, $endDate: Time!){
    viewer{accounts(filter:{accountTag:$accountTag}){r2OperationsAdaptiveGroups(limit:10000,filter:{datetime_geq:$startDate,datetime_leq:$endDate,bucketName:$bucketName}){
      sum{requests} dimensions{actionType}
    }}}
  }`;
  const bandwidthQuery=`query R2Bandwidth($accountTag: string!, $bucketName: string!, $startDate: Time!, $endDate: Time!){
    viewer{accounts(filter:{accountTag:$accountTag}){r2BandwidthUsageAdaptiveGroups(limit:1000,filter:{datetime_geq:$startDate,datetime_lt:$endDate,bucketName:$bucketName}){
      sum{bytesDownload bytesUpload}
    }}}
  }`;
  try{
    const base={accountTag,bucketName};
    const [detail,today,bw,...daily]=await Promise.all([
      gql(token,detailQuery,{...base,startDate:iso(five),endDate:iso(now)}),
      gql(token,summaryQuery,{...base,startDate:iso(startToday),endDate:iso(now)}),
      gql(token,bandwidthQuery,{...base,startDate:iso(startToday),endDate:iso(now)}),
      ...days.map(({s,e})=>gql(token,summaryQuery,{...base,startDate:iso(s),endDate:iso(e>now?now:e)}))
    ]);
    const detailGroups=detail?.viewer?.accounts?.[0]?.r2OperationsAdaptiveGroups||[];
    const todayGroups=today?.viewer?.accounts?.[0]?.r2OperationsAdaptiveGroups||[];
    const segment5m=segmentReads(detailGroups,prefix);
    const estimated=Math.max(0,Math.round(segment5m/30));
    const bandwidth=(bw?.viewer?.accounts?.[0]?.r2BandwidthUsageAdaptiveGroups||[]).reduce((a,x)=>a+Number(x?.sum?.bytesDownload||0),0);
    const dailyRows=daily.map((d,i)=>({
      date:days[i].s.toLocaleDateString('pt-BR',{timeZone:'America/Sao_Paulo'}),
      requests:requestSum(d?.viewer?.accounts?.[0]?.r2OperationsAdaptiveGroups||[])
    }));
    res.setHeader('Cache-Control','s-maxage=30, stale-while-revalidate=60');
    return res.status(200).json({
      source:'r2',
      estimated_now:estimated,
      segment_requests_5m:segment5m,
      requests_today:requestSum(todayGroups),
      download_bytes_today:bandwidth,
      daily:dailyRows,
      updated_at:new Date().toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'})
    });
  }catch(e){
    console.error('R2 analytics error',e.message);
    return res.status(502).json({error:'r2_analytics_unavailable'});
  }
}
