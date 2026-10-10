import React, { useEffect, useRef, useState } from 'react';
import { api, identify, useLive } from './api';
import { Brand, Donors, Levels, Icon, Poll, Question, Wheel, kinds } from './components';

export function Viewer() {
  const { state, connection, refresh } = useLive();
  const [tab,setTab] = useState('questions'), [kind,setKind] = useState('question'), [text,setText] = useState('');
  const [nickname,setNickname] = useState(''), [busy,setBusy] = useState(false), [notice,setNotice] = useState('');
  const [composer,setComposer] = useState(false);
  const [profile,setProfile] = useState(false);
  const dialog=useRef(null);
  useEffect(()=>{
    if(!composer && !profile)return;
    const before=document.activeElement;
    const node=dialog.current;
    node?.querySelector('input,textarea,select,button')?.focus();
    const key=event=>{
      if(event.key==='Escape'){setComposer(false);setProfile(false)}
      if(event.key==='Tab'){
        const items=[...node.querySelectorAll('button:not(:disabled),input,textarea,select,a[href]')];
        const first=items[0],last=items.at(-1);
        if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus()}
        else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus()}
      }
    };
    document.addEventListener('keydown',key);
    return()=>{document.removeEventListener('keydown',key);before?.focus()};
  },[composer,profile]);
  const me = state?.me;
  const allowed = Boolean(me && !state?.suspended);
  const notify = message => { setNotice(message); };
  const join = async event => {
    event.preventDefault(); setBusy(true);
    try { await identify(nickname); refresh(); setProfile(false); notify('Nombre actualizado. Tu identidad y tus votos se conservan.'); }
    catch(error) { notify(error.message); }
    finally { setBusy(false); }
  };
  const send = async event => {
    event.preventDefault(); setBusy(true);
    try { await api('viewer/submit',{kind,text}); setText(''); setComposer(false); notify('Enviado a revisión. Lo verás acá cuando Gerstep lo seleccione.'); }
    catch(error) { notify(error.message); }
    finally { setBusy(false); }
  };
  const command = async value => {
    if (!allowed) { setComposer(true); return; }
    try { await api('viewer/submit',{kind:'command',text:value}); notify('Comando enviado a revisión.'); }
    catch(error) { notify(error.message); }
  };
  const features = state?.features || {};
  const rows = state?.requests || [];
  const online = Boolean(state?.live?.connected);
  const stats = state?.live?.stats || {};
  return <div className="app-shell">
    <header className="topbar"><Brand/><div className="connection-info"><span className={`live-dot ${online?'on':''}`}/><strong>{online?'LIVE':'En espera'}</strong><span className="stream-handle">@{state?.live?.username || 'gerstep_official'}</span></div><button className="profile-button" onClick={()=>{setNickname(me?.nickname?.startsWith('Anónimo[')?'':me?.nickname||'');setProfile(true)}}><span className="avatar">{me?.nickname?.slice(0,1).toUpperCase() || '?'}</span><span>{me?.nickname || 'Conectando…'}</span></button></header>
    <div className="layout"><aside className="sidebar"><div className="nav-label">EL DIRECTO LO HACEMOS ACÁ</div><nav aria-label="Secciones">{[['questions','chat','Preguntas'],['poll','poll','Encuestas'],['donors','people','Comunidad']].map(([key,icon,label])=><button key={key} className={tab===key?'active':''} onClick={()=>setTab(key)}><Icon name={icon}/><span>{label}</span>{key==='poll' && state?.poll?.active && <span className="nav-dot"/>}</button>)}</nav><section className="command-bank"><div className="section-label"><Icon name="bolt" size={16}/>PARA MOVER LA COSA</div><p>Proponé un efecto. Gerstep le da el momento.</p><div className="command-buttons">{state?.commands?.filter(c=>c!=='!help').map(value=><button key={value} disabled={!features.command || state?.suspended} onClick={()=>command(value)}>{value}</button>)}</div></section><div className="sidebar-foot"><span className="tiny-status">{connection==='online'?'● Sincronizado':'○ Reconectando…'}</span><p>Un chat. Dos pantallas.<br/>La misma locura controlada.</p></div></aside>
    <main className="main-content">
      <div className="stream-summary"><span className="live-tag">{online?'EN DIRECTO':'ESPERANDO AL DIRECTO'}</span><span><Icon name="heart" size={15}/>{(stats.likes||0).toLocaleString('es')} likes</span><span><Icon name="chat" size={15}/>{(stats.comments||0).toLocaleString('es')} comentarios</span></div>
      {connection!=='online' && <div className="network-banner" role="status">Reconectando con el directo. Tus mensajes no se reenviarán solos.</div>}
      {state?.suspended && <div className="pause-banner" role="status">Gerstep pausó las interacciones. Podés seguir viendo el directo.</div>}
      {state?.identity_error && <div className="notice" role="alert">{state.identity_error}</div>}
      {notice && <div className="notice" role="status"><span>{notice}</span><button onClick={()=>setNotice('')} aria-label="Cerrar aviso"><Icon name="close" size={16}/></button></div>}
      <div className="content-heading"><div><span className="eyebrow">CHAT → MOMENTOS</span><h1>{tab==='questions'?'Abrí una buena pestaña.':tab==='poll'?'El chat decide.':'Bancando el directo.'}</h1><p>{tab==='questions'?'Preguntas y propuestas que merecen salir del chat.':tab==='poll'?'Votá acá o escribí /encuesta n en TikTok.':'Los aportes confirmados de la comunidad.'}</p></div>{tab==='questions' && <button className="primary compose-trigger" onClick={()=>setComposer(true)} disabled={state?.suspended}><Icon name="send" size={18}/><span>Proponer</span></button>}</div>
      {tab==='questions' ? <><div className="feed-label"><span>LA BANDEJA DEL DIRECTO</span><span>{rows.length} interacciones</span></div><div className="question-feed">{rows.length ? rows.map(item=><Question key={item.id} item={item} canAct={allowed} onError={notify}/>) : <div className="empty large"><div className="empty-window"><span/><span/><span/><code>/pregunta</code></div><h2>Todavía no abrimos esta pestaña.</h2><p>Dejá una pregunta o una idea absurda.<br/>Gerstep decide cuál merece el directo.</p><button className="primary" onClick={()=>setComposer(true)} disabled={state?.suspended}>Enviar la primera pregunta<Icon name="arrow" size={18}/></button></div>}</div><Wheel wheel={state?.wheel}/></> : tab==='poll' ? <Poll poll={state?.poll} myVote={state?.my_vote} canAct={allowed && features.poll} onError={notify}/> : <><Donors donors={state?.donors}/><Levels rows={state?.levels}/></>}
    </main>
    <aside className="right-rail"><Poll poll={state?.poll} myVote={state?.my_vote} canAct={allowed && features.poll} onError={notify}/><Donors donors={state?.donors}/><Levels rows={state?.levels}/><div className="rail-note"><code>STATUS: TRANQUILO</code><p>No todo merece un efecto.<br/>Cuando lo merece, se nota.</p></div></aside></div>
    <nav className="mobile-nav" aria-label="Navegación móvil">{[['questions','chat','Preguntas'],['poll','poll','Encuestas'],['donors','people','Comunidad']].map(([key,icon,label])=><button key={key} className={tab===key?'active':''} onClick={()=>setTab(key)}><Icon name={icon}/><span>{label}</span></button>)}<button onClick={()=>setComposer(true)} disabled={state?.suspended}><Icon name="send"/><span>Proponer</span></button></nav>
    {composer && <div className="modal-backdrop" onClick={event=>{if(event.target===event.currentTarget)setComposer(false)}}><section ref={dialog} className="composer" role="dialog" aria-modal="true" aria-labelledby="composer-title"><button className="close-modal" aria-label="Cerrar formulario" onClick={()=>setComposer(false)}><Icon name="close"/></button><span className="eyebrow">DIRECTO A LA BANDEJA</span><h2 id="composer-title">¿Qué hacemos con esto?</h2><p>Puede ser una gran pregunta. O una idea que no debería funcionar.</p>
      {!me ? <p role="status">Preparando tu identidad anónima…</p> : <form onSubmit={send}><div className="type-selector">{Object.entries(kinds).filter(([key])=>features[key] && (key!=='music' || state?.live?.music_enabled)).map(([key,label])=><button type="button" key={key} className={kind===key?'active':''} onClick={()=>{setKind(key);setText('')}}>{label}</button>)}</div><label htmlFor="message">{kind==='music'?'Enlace de YouTube aprobado':kind==='command'?'Comando permitido':'Contá la idea completa'}</label>{kind==='command' ? <select id="message" value={text} onChange={event=>setText(event.target.value)} required><option value="">Elegí un comando</option>{state?.commands?.map(value=><option key={value}>{value}</option>)}</select> : <textarea id="message" autoFocus value={text} onChange={event=>setText(event.target.value)} maxLength={kind==='question'?(state?.max_length||1200):800} minLength={3} required rows={kind==='music'?3:6} placeholder={kind==='music'?'https://www.youtube.com/watch?v=…':'¿Qué querés preguntarle o proponerle a Gerstep?'}/>}
      <div className="composer-foot"><span>Revisión antes de aparecer en el LIVE</span><span>{text.length}/{kind==='question'?(state?.max_length||1200):800}</span></div><button className="primary full" disabled={busy || !features[kind] || state?.suspended || !text.trim()}>{busy?'Enviando…':'Enviar a revisión'}<Icon name="send" size={18}/></button><p className="micro">Esperá {state?.cooldown || 20} s entre propuestas. Los comandos y la música también pasan por moderación.</p></form>}
      {notice && <div className="form-message" role="status">{notice}</div>}
    </section></div>}
    {profile && <div className="modal-backdrop" onClick={event=>{if(event.target===event.currentTarget)setProfile(false)}}><section ref={dialog} className="composer" role="dialog" aria-modal="true" aria-labelledby="profile-title"><button className="close-modal" aria-label="Cerrar perfil" onClick={()=>setProfile(false)}><Icon name="close"/></button><span className="eyebrow">TU IDENTIDAD EN ESTA PÁGINA</span><h2 id="profile-title">Anónimo o con apodo.</h2><p>Tu token conserva tus interacciones en este navegador. Cambiar el nombre no crea otro voto.</p><form onSubmit={join}><label htmlFor="nickname">Apodo opcional</label><input id="nickname" value={nickname} onChange={event=>setNickname(event.target.value)} maxLength={24} minLength={2} autoComplete="nickname" placeholder="Dejalo vacío para seguir anónimo"/><button className="primary full" disabled={busy}>Guardar nombre</button></form><p className="micro">El apodo no acredita una cuenta de TikTok. No compartas el token de tu navegador.</p>{notice && <p role="status">{notice}</p>}</section></div>}
  </div>;
}

export function Overlay() {
  const {state} = useLive();
  const active = !state?.suspended ? state?.active : null;
  return <div className="obs-surface">{active && <section className="obs-question" key={active.id}><div className="obs-label"><span className="brand-mark">G</span><span>PREGUNTA DEL CHAT</span><span className="obs-status">{active.status==='answered'?'Respondida':'Seleccionada'}</span></div><h1>{active.text.slice(0,400)}{active.text.length>400?'…':''}</h1><div className="obs-author">{active.nickname}<span>GERSTEP INTERACTIVE</span></div></section>}{state?.poll?.active && !state.suspended && <div className="obs-poll"><strong>{state.poll.title}</strong>{state.poll.options.map(item=><span key={item.number}>{item.number}. {item.label} · {item.votes}</span>)}<code>/encuesta n</code></div>}</div>;
}
