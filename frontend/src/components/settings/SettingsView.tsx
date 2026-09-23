import { createContext, useContext, type ReactNode } from 'react';

const ActiveSettingsView = createContext(true);

export function SettingsView({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <ActiveSettingsView.Provider value={active}>
      <div className="settings-view" hidden={!active} inert={!active}>
        {children}
      </div>
    </ActiveSettingsView.Provider>
  );
}

export function useSettingsView() {
  return useContext(ActiveSettingsView);
}
