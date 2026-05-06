export type DetailTab = {
  id: string;
  label: string;
  enabled?: boolean;
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
          aria-disabled={tab.enabled === false}
          disabled={tab.enabled === false}
          className={`${activeTab === tab.id ? 'active' : ''} ${tab.enabled === false ? 'disabled' : ''}`}
          onClick={() => {
            if (tab.enabled !== false) onChange(tab.id);
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
