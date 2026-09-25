import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Boxes, ChevronRight, Compass, MessageSquarePlus, MoreHorizontal, Settings2, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { SidebarGroup, SidebarGroupLabel, SidebarMenu, SidebarMenuAction, SidebarMenuButton, SidebarMenuItem,
  SidebarMenuSub, SidebarMenuSubButton, SidebarMenuSubItem, useSidebar } from '@/components/ui/sidebar';
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { cn } from '@/lib/utils';
import { useProjectsStore } from '../../store/useProjectsStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import type { Project } from '../../types/projects';
import type { SettingsNavigate } from '../settings/navigation';
import { ResourceLoading, errorText } from '../settings/resources/ResourceUI';
import { projectUrl } from './navigation';

type TreeActions = {
  onNavigate: SettingsNavigate;
  onSelectSession: (id: string, projectId: string | null) => Promise<boolean>;
  onCreateSession: (projectId?: string | null) => Promise<boolean>;
  onSessionDeleted: (id: string) => void;
  onProjectDeleted: (id: string) => void;
};

export function ProjectsTree(props: TreeActions) {
  const { t } = useTranslation('personas');
  const projects = useProjectsStore((state) => state.projects);
  return <SidebarGroup>
    <SidebarGroupLabel>{t('projects')}</SidebarGroupLabel>
    <SidebarMenu>
      {projects.map((project) => <ProjectItem key={project.id} project={project} {...props} />)}
    </SidebarMenu>
    {!projects.length ? <p className="model-empty px-2">{t('noProjects')}</p> : null}
  </SidebarGroup>;
}

function ProjectItem({ project, onNavigate, onSelectSession, onCreateSession, onSessionDeleted, onProjectDeleted }: TreeActions & { project: Project }) {
  const { t } = useTranslation('personas');
  const { confirm, confirmation } = useConfirmDialog();
  const { setOpenMobile } = useSidebar();
  const currentProjectId = useCogitaStore((state) => state.currentProjectId);
  const current = useCogitaStore((state) => state.currentSession);
  const allSessions = useCogitaStore((state) => state.sessions);
  const reloadSessions = useCogitaStore((state) => state.reloadSessions);
  const [expanded, setExpanded] = useState(currentProjectId === project.id);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [deleting, setDeleting] = useState<string | null>(null);
  const sessions = allSessions.filter((session) => session.project_id === project.id);
  const active = currentProjectId === project.id;
  useEffect(() => { if (active) setExpanded(true); }, [active]);
  useEffect(() => {
    if (!expanded || project.kind !== 'workspace') return;
    let live = true;
    setLoading(true); setError('');
    void reloadSessions(project.id).catch((reason) => { if (live) setError(errorText(reason)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [expanded, project.id, project.kind, reload, reloadSessions]);
  const openSettings = async () => { if (await onNavigate(projectUrl(project.id))) setOpenMobile(false); };
  async function deleteProject() {
    if (!(await confirm(t('deleteProjectConfirm', { name: project.name }), { destructive: true }))) return;
    setDeleting(project.id);
    try {
      await useProjectsStore.getState().remove(project.id);
      useCogitaStore.getState().forgetProject(project.id);
      onProjectDeleted(project.id);
    } catch (reason) { useCogitaStore.getState().setError(errorText(reason)); setDeleting(null); }
  }
  async function deleteSession(id: string) {
    if (!(await confirm(t('deleteSessionConfirm'), { destructive: true }))) return;
    setDeleting(id);
    await useCogitaStore.getState().deleteSession(id);
    if (!useCogitaStore.getState().sessions.some((session) => session.session_id === id)) onSessionDeleted(id);
    setDeleting(null);
  }
  const Icon = project.kind === 'workspace' ? Compass : Boxes;
  return <SidebarMenuItem data-project-id={project.id}>
    <Collapsible open={expanded} onOpenChange={setExpanded}>
      <div className="relative flex items-center">
        {project.kind === 'workspace' ? <CollapsibleTrigger render={<Button type="button" variant="ghost" size="icon"
          className="shrink-0" aria-label={t('toggleProject', { name: project.name })} />}>
          <ChevronRight className={cn('transition-transform', expanded && 'rotate-90')} />
        </CollapsibleTrigger> : null}
        <SidebarMenuButton type="button" className="project-select" isActive={active && !current}
          aria-current={active && !current ? 'page' : undefined} title={project.name} onClick={() => void openSettings()} disabled={deleting === project.id}>
          <Icon data-icon="inline-start" /><span>{project.name}</span>
        </SidebarMenuButton>
        <DropdownMenu>
          <DropdownMenuTrigger render={<SidebarMenuAction type="button" aria-label={t('projectActions', { name: project.name })} />}><MoreHorizontal /></DropdownMenuTrigger>
          <DropdownMenuContent align="end"><DropdownMenuGroup>
            <DropdownMenuItem onClick={() => void openSettings()}><Settings2 data-icon="inline-start" />{t('projectSettings')}</DropdownMenuItem>
            <DropdownMenuItem variant="destructive" disabled={!!deleting} onClick={() => void deleteProject()}><Trash2 data-icon="inline-start" />{t('deleteProject')}</DropdownMenuItem>
          </DropdownMenuGroup></DropdownMenuContent>
        </DropdownMenu>
      </div>
      {project.kind === 'workspace' ? <CollapsibleContent>
        <SidebarMenuSub>
          <SidebarMenuSubItem>
            <SidebarMenuSubButton render={<button type="button" />} className="w-full" onClick={async () => { if (await onCreateSession(project.id)) setOpenMobile(false); }}>
              <MessageSquarePlus data-icon="inline-start" /><span>{t('newSession')}</span>
            </SidebarMenuSubButton>
          </SidebarMenuSubItem>
          {sessions.map((session) => {
            const title = session.title.trim() || t('newSession');
            const selected = current?.session_id === session.session_id;
            return <SidebarMenuSubItem key={session.session_id} className={cn('session-item group/menu-item', selected && 'selected')}>
              <SidebarMenuSubButton render={<button type="button" disabled={deleting === session.session_id} />}
                className="session-select w-full pr-8" isActive={selected} aria-current={selected ? 'page' : undefined} title={title}
                onClick={async () => { if (await onSelectSession(session.session_id, project.id)) setOpenMobile(false); }}><span>{title}</span></SidebarMenuSubButton>
              <DropdownMenu>
                <DropdownMenuTrigger render={<SidebarMenuAction type="button" className="session-menu" showOnHover aria-label={t('sessionActions', { title })} />}><MoreHorizontal /></DropdownMenuTrigger>
                <DropdownMenuContent align="end"><DropdownMenuGroup>
                  <DropdownMenuItem variant="destructive" disabled={!!deleting} onClick={() => void deleteSession(session.session_id)}>
                    <Trash2 data-icon="inline-start" />{t('deleteSession')}
                  </DropdownMenuItem>
                </DropdownMenuGroup></DropdownMenuContent>
              </DropdownMenu>
            </SidebarMenuSubItem>;
          })}
          {loading || error ? <SidebarMenuSubItem><ResourceLoading error={error} retry={() => setReload((n) => n + 1)} /></SidebarMenuSubItem> : null}
          {!loading && !error && !sessions.length ? <SidebarMenuSubItem><p className="model-empty px-2">{t('noProjectSessions')}</p></SidebarMenuSubItem> : null}
        </SidebarMenuSub>
      </CollapsibleContent> : null}
    </Collapsible>
    {confirmation}
  </SidebarMenuItem>;
}
