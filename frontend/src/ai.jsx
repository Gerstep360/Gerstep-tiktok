import React, {useEffect,useState} from 'react';
import {api} from './api';

export function AdminAI(){
  const [state,setState]=useState(null),[text,setText]=useState(''),[messages,setMessages]=useState([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{let alive=true;api('admin/ai').then(data=>{if(alive)setState(data)}).catch(err=>{if(alive)setError(err.message)});return()=>{alive=false}},[]);
  async function send(event){
    event.preventDefault();if(busy||!text.trim())return;
    const value=text.trim();setBusy(true);setError('');setText('');
    setMessages(old=>[...old.slice(-18),{role:'Vos',text:value}]);
    try{
      const result=await api('admin/ai',{text:value});
      setMessages(old=>[...old.slice(-18),{role:result.source==='nvidia'?'Gerstep AI':result.source==='fallback'?'Respuesta local · NVIDIA no disponible':'Respuesta local',text:result.text}]);
      setState(old=>({...old,quota:result.quota}));
      await api('admin/ai',{action:'ack',id:result.id});
    }catch(err){setError(err.message)}finally{setBusy(false)}
  }
  return <section className="admin-panel ai-panel"><span className="eyebrow">LABORATORIO PRIVADO</span><h1>Probá una idea.</h1><p>Conversá con Gerstep sin enviar nada al LIVE. Solo tu sesión de administrador puede usar este chat. Los comandos de acciones no se ejecutan.</p>
    <div className="ai-health"><span className={`connection ${state?.configured&&state?.enabled?'online':''}`}>{state?.configured&&state?.enabled?'NVIDIA configurada':'Modo local · falta activar NVIDIA'}</span><small>{state?.model}</small><small>{state?.quota?.requests_window||0} solicitudes en la última ventana</small><button className="text-button" disabled={busy} onClick={async()=>{try{await api('admin/ai',{action:'clear'});setMessages([])}catch(err){setError(err.message)}}}>Limpiar contexto</button></div>
    <div className="ai-conversation" role="log" aria-label="Conversación de prueba" aria-live="polite">{messages.length?messages.map((message,index)=><article className={message.role==='Vos'?'ai-message own':'ai-message'} key={index}><strong>{message.role}</strong><p>{message.text}</p></article>):<div className="empty"><h2>Una pregunta antes de salir al aire.</h2><p>Probá !chisme, !opina o una pregunta de programación. !help responde sin gastar tokens.</p></div>}</div>
    {error&&<p className="notice" role="alert">{error}</p>}
    <form className="ai-compose" onSubmit={send}><label htmlFor="ai-text">Mensaje o comando</label><textarea id="ai-text" value={text} onChange={event=>setText(event.target.value)} rows={3} maxLength={700} placeholder="!chisme sobre un NPC que pidió aumento" required/><div><span className="micro">{text.length}/700 · Sin voz ni acciones sobre el PC</span><button className="primary" disabled={busy||!text.trim()}>{busy?'Gerstep está pensando…':'Probar respuesta'}</button></div></form>
  </section>;
}
