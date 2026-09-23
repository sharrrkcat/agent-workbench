import React from 'react';
import ReactDOM from 'react-dom/client';
import App from '@/App';
import { TooltipProvider } from '@/components/ui/tooltip';
import './i18n';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <TooltipProvider>
      <App />
    </TooltipProvider>
  </React.StrictMode>,
);
