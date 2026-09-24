import { useTranslation } from 'react-i18next';
import { FileText, Play } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem } from '@/components/ui/dropdown-menu';
import type { SiglipTower, SiglipTowers } from '../../../types/models';
import { useSettingsView } from '../SettingsView';

export function TowerActionMenu({ action, disabled, onSelect }: {
  action: 'load' | 'log'; disabled: boolean; onSelect: (tower: SiglipTower) => void;
}) {
  const { t } = useTranslation('llm');
  const activeView = useSettingsView();
  const Icon = action === 'load' ? Play : FileText;
  const label = t(action === 'load' ? 'load' : 'processLog');
  return (
    <DropdownMenu key={String(activeView)}>
      <DropdownMenuTrigger render={<Button type="button" variant="ghost" size="icon"
        disabled={disabled} aria-label={label} title={label} />}>
        <Icon data-icon="inline-start" />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="min-w-48" align="end">
        <DropdownMenuGroup>
          {(['image', 'text'] as const).map((tower) => <DropdownMenuItem key={tower} onClick={() => onSelect(tower)}>
            {t(`siglip.${action}.${tower}`)}
          </DropdownMenuItem>)}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function SiglipStatus({ towers }: { towers: SiglipTowers }) {
  const { t } = useTranslation('llm');
  return (
    <div className="flex min-w-0 basis-full flex-col gap-2" role="group" aria-label={t('siglip.towers')}>
      <div className="flex flex-wrap gap-2">
        {(['image', 'text'] as const).map((tower) => <Badge key={tower}
          variant={towers[tower].error_code ? 'destructive' : 'secondary'}>
          {t('siglip.tower.' + tower)}: {t('siglip.states.' + towers[tower].process_state)}
          {towers.active_tower === tower ? ` · ${t('active')}` : ''}
          {towers[tower].error_code ? ` · ${towers[tower].error_code}` : ''}
        </Badge>)}
      </div>
      {towers.model_revision ? <dl className="grid min-w-0 gap-1 text-xs">
        <div className="flex gap-1"><dt>{t('params.dimensions')}:</dt><dd>{towers.dimensions ?? t('siglip.pending')}</dd></div>
        <div><dt>{t('siglip.revision')}</dt><dd><code className="wrap-anywhere">{towers.model_revision}</code></dd></div>
        <div><dt>{t('siglip.vectorSpace')}</dt><dd><code className="wrap-anywhere">{towers.vector_space_id ?? t('siglip.pending')}</code></dd></div>
      </dl> : null}
    </div>
  );
}
