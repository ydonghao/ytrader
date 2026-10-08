import React from 'react';
import ReactDOM from 'react-dom/client';
import {BrowserRouter} from 'react-router-dom';
import {App} from './App';
import {installFetchCache} from './lib/fetchCache';
import './styles/global.css';

// GET 缓存层先于渲染安装（切菜单瞬时回显，mutation 后自动失效）
installFetchCache();

const root = document.getElementById('root');

if (root) {
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </React.StrictMode>
  );
}
