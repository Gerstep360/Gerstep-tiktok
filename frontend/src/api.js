import { useCallback, useEffect, useRef, useState } from 'react';
export const BASE = import.meta.env.BASE_URL;
export async function api(path, data) {
  const response = await fetch(`${BASE}api/${path}`, {
    method: data === undefined ? 'GET' : 'POST', credentials: 'same-origin',
    headers: data === undefined ? {} : { 'Content-Type': 'application/json' },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  let value;
  try { value = await response.json(); } catch { value = { error: `Error de conexión (${response.status}).` }; }
  if (!response.ok) { const error = new Error(value.error || 'No se pudo completar la solicitud.'); error.status=response.status; throw error; }
  return value;
}

const IDENTITY_KEY = `gerstep:${BASE}:visitor`;
export async function identify(nickname) {
  let token;
  try { token=localStorage.getItem(IDENTITY_KEY) || undefined; } catch { /* Cookies still support private browsing. */ }
  let identity;
  try { identity=await api('session',{token,nickname}); }
  catch(error) {
    if (!token || error.status!==400) throw error;
    try { localStorage.removeItem(IDENTITY_KEY); } catch { /* Storage may be unavailable. */ }
    identity=await api('session',{nickname});
  }
  if(identity.token) try { localStorage.setItem(IDENTITY_KEY,identity.token); } catch { /* HttpOnly cookie remains usable. */ }
  return identity;
}

export function useLive(role = 'viewer') {
  const [state, setState] = useState(null);
  const [connection, setConnection] = useState('connecting');
  const [version, setVersion] = useState(0);
  const socket = useRef(null);
  const refresh = useCallback(() => setVersion(value => value + 1), []);
  useEffect(() => {
    let closed = false, timer, attempts = 0;
    let identified = false;
    const connect = async () => {
      try {
        let identityError=null;
        if(role==='viewer' && !identified && !location.pathname.replace(/\/$/,'').endsWith('/overlay')) {
          try {await identify(); identified=true;} catch(error){identityError=error.message}
        }
        const data = await api(role === 'admin' ? 'admin/state' : 'state');
        if (closed) return;
        setState({...data,identity_error:identityError});
      } catch (error) {
        if (closed) return;
        if (role === 'admin' && error.status===401) { setState(null);setConnection('auth'); return; }
      }
      if (closed) return;
      const url = new URL(`${BASE}api/${role}/ws`, location.origin);
      url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(url);
      socket.current = ws;
      ws.onopen = () => { attempts = 0; setConnection('online'); };
      ws.onmessage = event => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'state') setState(previous => ({ ...previous, ...message.patch }));
        } catch { /* A malformed update never executes or changes UI state. */ }
      };
      ws.onclose = () => {
        if (closed) return;
        setConnection('reconnecting');
        timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** attempts++) + Math.random() * 300);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => { closed = true; clearTimeout(timer); socket.current?.close(); };
  }, [role, version]);
  return { state, connection, refresh };
}
