// Read-only preview diagnostics; does not change the streaming server.
export default async function handler(req,res) {
  res.setHeader('Cache-Control','no-store');
  const upstream='https://pub-5f56eb102f284301a06abb9ec674001d.r2.dev/alce-test/live.m3u8';
  const origin='https://radioalce-91wjbg9xh-luizamedice-2069s-projects.vercel.app';
  try {
    const response=await fetch(upstream,{headers:{Origin:origin},signal:AbortSignal.timeout(10000),cache:'no-store'});
    const body=await response.text();
    res.status(200).json({
      upstream_http:response.status,
      is_playlist:body.startsWith('#EXTM3U'),
      access_control_allow_origin:response.headers.get('access-control-allow-origin'),
      access_control_expose_headers:response.headers.get('access-control-expose-headers'),
      content_type:response.headers.get('content-type'),
      has_segments:body.includes('.ts'),
      playlist_lines:body.split('\n').filter(line=>line.startsWith('#EXT-X-')).slice(0,12)
    });
  } catch(error) { res.status(200).json({request_error:error.name || 'network-error',message:String(error.message).slice(0,180)}) }
}