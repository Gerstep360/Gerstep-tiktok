import React, { useEffect, useState } from 'react';
import { api } from './api';

export function Icon({ name, size = 20 }) {
  const paths = {
    chat: <><path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-6 4V6a2 2 0 0 1 2-2Z"/><path d="M7 9h10M7 13h6"/></>,
    heart: <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>,
    poll: <><path d="M4 21V11h4v10M10 21V3h4v18M16 21V7h4v14"/></>,
    bolt: <path d="m13 2-9 12h7l-1 8 10-12h-7l0-8Z"/>,
    music: <><path d="M9 18V5l12-3v13M9 8l12-3"/><ellipse cx="6" cy="18" rx="3" ry="3"/><ellipse cx="18" cy="15" rx="3" ry="3"/></>,
    send: <><path d="m3 3 19 9-19 9 4-9-4-9ZM7 12h15"/></>,
    people: <><circle cx="9" cy="7" r="4"/><path d="M2 21v-3a7 7 0 0 1 14 0v3M16 4a4 4 0 0 1 0 8M19 15a6 6 0 0 1 3 6"/></>,
    close: <path d="m6 6 12 12M18 6 6 18"/>,
    arrow: <path d="m9 5 7 7-7 7"/>,
    check: <path d="m5 12 4 4L19 6"/>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.bolt}</svg>;
}

export const labels = { pending: 'En revisión', approved: 'Aprobada', selected: 'Seleccionada', answered: 'Respondida', rejected: 'No seleccionada', error: 'No se pudo realizar' };
export const kinds = { question: 'Pregunta', proposal: 'Propuesta', command: 'Comando', music: 'Música' };

export function Brand() {
  return <a className="brand" href={import.meta.env.BASE_URL} aria-label="Gerstep Interactive, inicio"><span className="brand-mark">G<span className="brand-dot"/></span><span>GERSTEP<small>INTERACTIVE</small></span></a>;
}

export function Question({ item, canAct, onError }) {
  const [expanded, setExpanded] = useState(false), [supported, setSupported] = useState(false), [busy, setBusy] = useState(false);
  const support = async () => {
    setBusy(true);
    try { await api('viewer/support', { id: item.id }); setSupported(true); }
    catch (error) { onError(error.message); }
    finally { setBusy(false); }
  };
  const status = item.kind === 'music' && item.status === 'answered' ? 'En cola de música' : labels[item.status];
  return <article className={`question ${item.status === 'selected' ? 'selected' : ''}`}>
    <div className="question-meta"><span className="avatar">{item.nickname.slice(0,1).toUpperCase()}</span><strong>{item.nickname}</strong><span className="kind">{kinds[item.kind]}</span><span className={`status ${item.status}`}>{status}</span></div>
    <p className={!expanded ? 'clamp' : ''}>{item.text}</p>
    {item.text.length > 220 && <button className="text-button" onClick={() => setExpanded(!expanded)}>{expanded ? 'Ver menos' : 'Leer completa'}</button>}
    {item.response && <p className="response"><span>Gerstep</span>{item.response}</p>}
    <div className="question-footer"><span>{new Date(item.created*1000).toLocaleTimeString('es', {hour:'2-digit',minute:'2-digit'})}</span><button className={`support ${supported ? 'supported' : ''}`} onClick={support} disabled={!canAct || busy || supported || !['approved','selected'].includes(item.status)} aria-label={`Apoyar la pregunta de ${item.nickname}`}><Icon name="heart" size={16}/>{item.supports}<span>{supported ? 'Apoyada' : 'Apoyar'}</span></button></div>
  </article>;
}

export function Poll({ poll, myVote, canAct, onError }) {
  const [choice, setChoice] = useState(null), [busy, setBusy] = useState(false);
  useEffect(()=>setChoice(myVote?.poll_id===poll?.id?myVote.choice:null),[poll?.id,myVote?.poll_id,myVote?.choice]);
  const vote = async number => {
    setBusy(true);
    try { await api('viewer/vote', {choice:number,poll_id:poll.id}); setChoice(number); }
    catch(error) { onError(error.message); }
    finally { setBusy(false); }
  };
  return <section className="poll-panel"><div className="section-label"><Icon name="poll" size={16}/>{poll?.active ? 'DECIDE EL CHAT' : 'ENCUESTAS'}</div>
    {!poll ? <div className="empty small"><strong>El chat tiene voto.</strong><p>La próxima encuesta aparecerá acá y en TikTok.</p></div> : <>
      <h3>{poll.title}</h3><div className="poll-options">{poll.options.map(option => {
        const percentage = poll.total ? Math.round(option.votes/poll.total*100) : 0;
        return <button key={option.number} className={`poll-option ${choice === option.number ? 'voted' : ''}`} disabled={!canAct || !poll.active || busy} onClick={() => vote(option.number)}><span className="poll-fill" style={{width:`${percentage}%`}}/><span className="option-number">{option.number}</span><span className="option-label">{option.label}</span><span className="percentage">{percentage}%</span></button>;
      })}</div><div className="poll-caption">{poll.total} votos <span>{poll.active ? <>En TikTok: <code>/encuesta n</code></> : 'Encuesta cerrada'}</span></div><p className="micro">Un voto web por IP y encuesta. {choice ? `Tu opción registrada: ${choice}.` : 'Tu identidad se conserva al volver.'}</p>
    </>}
  </section>;
}

export function Levels({ rows=[] }) {
  return <section className="donors-panel"><div className="section-label"><Icon name="chat" size={16}/>NIVELES DEL CHAT</div>{rows.length ? <ol className="donors">{rows.map((row,index)=><li key={index}><span className="donor-order">{String(index+1).padStart(2,'0')}</span><span className="avatar">{row.nickname.slice(0,1).toUpperCase()}</span><strong>{row.nickname}<small className="level-rank">{row.rank}</small></strong><span className="coins">{row.level}<small>nivel</small></span></li>)}</ol> : <div className="empty small"><strong>Los niveles llegan con el chat.</strong><p>Se sincronizan desde los perfiles de TikTok por su ID estable.</p></div>}<p className="micro">Progreso existente del chat, actualizado cada 30 s. El apodo web no modifica estos perfiles.</p></section>;
}

export function Donors({ donors }) {
  const [scope,setScope] = useState('stream');
  const rows = donors?.[scope] || [];
  return <section className="donors-panel"><div className="section-label"><Icon name="people" size={16}/>QUIENES BANCAN EL DIRECTO</div><div className="segmented"><button className={scope==='stream'?'active':''} onClick={() => setScope('stream')}>Este stream</button><button className={scope==='global'?'active':''} onClick={() => setScope('global')}>Global</button></div>
    {rows.length ? <ol className="donors">{rows.map((row,index)=><li key={`${row.nickname}-${index}`}><span className="donor-order">{String(index+1).padStart(2,'0')}</span><span className="avatar">{row.nickname.slice(0,1).toUpperCase()}</span><strong>{row.nickname}</strong><span className="coins">{row.coins.toLocaleString('es')}<small>monedas</small></span></li>)}</ol> : <div className="empty small"><strong>Todavía no hay regalos registrados.</strong><p>Los aportes de TikTok aparecen cuando llega un evento confirmado.</p></div>}
    <p className="micro">Aportes reales recibidos. Los apodos web no verifican una cuenta de TikTok.</p>
  </section>;
}

export function Wheel({ wheel }) {
  if (!wheel) return null;
  const selected = wheel.candidates.find(item => item.id === wheel.selected);
  return <section className="wheel-panel" key={wheel.id}><div className="section-label">LA PRÓXIMA PREGUNTA</div><div className="wheel"><div className="wheel-disc"/><span className="wheel-center"><Icon name="chat" size={30}/></span><span className="wheel-pointer"/></div><div className="wheel-result"><small>La ruleta eligió</small><strong>{selected?.nickname}</strong><p>{selected?.text}</p><span>Gerstep decide cuándo responder.</span></div></section>;
}
