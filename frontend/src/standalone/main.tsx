import React, { useCallback, useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import FarklePage from '@/components/playground/farkle/FarklePage';
import { SidebarProvider } from '@/components/ui/sidebar';
import { TooltipProvider } from '@/components/ui/tooltip';
import './i18n';
import './styles.css';

function FarkleApp() {
  const [search, setSearch] = useState(window.location.search);
  useEffect(() => {
    const changed = () => setSearch(window.location.search);
    window.addEventListener('popstate', changed);
    return () => window.removeEventListener('popstate', changed);
  }, []);
  const navigate = useCallback(async (url: string) => {
    const target = new URL(url, window.location.href);
    if (target.href !== window.location.href) window.history.pushState(null, '', target);
    setSearch(target.search);
    return true;
  }, []);
  return <SidebarProvider className="h-dvh min-h-0 overflow-hidden">
    <FarklePage search={search} onNavigate={navigate} />
  </SidebarProvider>;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><TooltipProvider><FarkleApp /></TooltipProvider></React.StrictMode>,
);
