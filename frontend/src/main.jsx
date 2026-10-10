import React from 'react';
import { createRoot } from 'react-dom/client';
import { Viewer, Overlay } from './viewer';
import { Admin } from './admin';
import './style.css';

const path = location.pathname.replace(/\/$/, '');
const Surface = path.endsWith('/admin') || path.endsWith('/login') ? Admin : path.endsWith('/overlay') ? Overlay : Viewer;
createRoot(document.getElementById('root')).render(<Surface/>);
