import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

const server=await createServer({server:{middlewareMode:true},appType:'custom'});
after(()=>server.close());
const {Viewer}=await server.ssrLoadModule('/src/viewer.jsx');
const {Admin}=await server.ssrLoadModule('/src/admin.jsx');
const {Question,Poll,Levels,Wheel}=await server.ssrLoadModule('/src/components.jsx');
const {StudioConnection}=await server.ssrLoadModule('/src/connection.jsx');
const render=(Component,props={})=>renderToStaticMarkup(React.createElement(Component,props));

test('private connection help distinguishes VPS intake from PC audio',()=>{
  const disconnected=render(StudioConnection,{online:false,live:{connected:true}});
  assert.ok(disconnected.includes('PC sin conectar'));
  assert.ok(disconnected.includes('TikTok pendiente en el PC'));
  assert.ok(disconnected.includes('api/admin/connection'));
  const connected=render(StudioConnection,{online:true,live:{connected:true}});
  assert.ok(connected.includes('TikTok conectado en el PC'));
  assert.ok(connected.includes('Usar bot'));
});

test('public surface has no admin link or mandatory nickname entry',()=>{
  const html=render(Viewer);
  assert.ok(!html.includes('href="/Gerstep/admin"'));
  assert.ok(!html.includes('Panel de Gerstep'));
  assert.ok(!html.includes('id="nickname"'));
  assert.ok(html.includes('Navegación móvil'));
});
test('private login requires its own password',()=>{
  const html=render(Admin);
  assert.ok(html.includes('type="password"'));
  assert.ok(html.includes('Cabina del directo.'));
  assert.ok(!html.includes('Bandeja del directo.'));
});
test('viewer text is escaped, never executed as HTML',()=>{
  const html=render(Question,{item:{id:'test',nickname:'<script>alert(1)</script>',kind:'question',text:'<img src=x onerror=alert(1)>',status:'approved',created:1,supports:0}});
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<img'));
});
test('poll, authoritative levels and question roulette render received data',()=>{
  const poll=render(Poll,{poll:{id:'poll',title:'¿Error o reinicio?',active:true,total:3,options:[{number:1,label:'Error',votes:2},{number:2,label:'Reinicio',votes:1}]},canAct:true});
  assert.ok(poll.includes('67%'));
  assert.ok(poll.includes('Un voto web por IP'));
  assert.ok(render(Levels,{rows:[{nickname:'Real',level:3,rank:'Rango real'}]}).includes('Rango real'));
  assert.ok(render(Wheel,{wheel:{id:'wheel',selected:'q',candidates:[{id:'q',nickname:'Real',text:'Pregunta aprobada'}]}}).includes('Pregunta aprobada'));
});
