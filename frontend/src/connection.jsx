import React from 'react';
import { BASE } from './api';

export function StudioConnection({ online, live }) {
  return <section className="studio-connection" aria-labelledby="studio-connection-title">
    <div className="section-label">WEB + PROGRAMA DEL PC</div>
    <h2 id="studio-connection-title">Una conexión para el directo.</h2>
    <div className="connection-stages" role="status">
      <span className="ready">Web activa</span>
      <span className={online ? 'ready' : ''}>{online ? 'PC conectado' : 'PC sin conectar'}</span>
      <span className={online && live?.connected ? 'ready' : ''}>{online && live?.connected ? 'TikTok conectado en el PC' : 'TikTok pendiente en el PC'}</span>
    </div>
    <p>{online ? 'El programa conserva la voz, la música y sus colas. Las preguntas se leen cuando elegís Usar bot.' : 'Conectá el programa del PC para usar el bot. El lector del VPS recibe eventos; la voz se reproduce en tu PC.'}</p>
    <a className="secondary" href={`${BASE}api/admin/connection`} download>Descargar conexión para el PC</a>
    <p className="micro">En el programa: Interactive → Importar conexión VPS. Elegí el archivo descargado y conectá TikTok. El archivo contiene claves privadas; guardalo para vos.</p>
  </section>;
}
