export type DetailTab = {
  id: string;
  label: string;
};

export function DetailTabs({
  tabs,
  activeTab,
  onChange,
}: {
  tabs: DetailTab[];
  activeTab: string;
  onChange: (tab: string) => void;
}) {
  return (
    <div className="detail-tabs" role="tablist" aria-label="Detail sections">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          className={activeTab === tab.id ? 'active' : ''}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
