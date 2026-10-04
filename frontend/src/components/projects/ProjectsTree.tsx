import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Bot, Boxes, Compass, MessageSquarePlus, MoreHorizontal, Settings2, Trash2 } from 'lucide-react';
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
  const targetId = useCogitaStore((state) => state.sessionLoad?.sessionId);
  const allSessions = useCogitaStore((state) => state.sessions);
  const reloadSessions = useCogitaStore((state) => state.reloadSessions);
  const [expanded, setExpanded] = useState(currentProjectId === project.id);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [deleting, setDeleting] = useState<string | null>(null);
  const sessions = allSessions.filter((session) => session.project_id === project.id);
  const active = currentProjectId === project.id;
  useEffect(() => { if (active) setExpanded(true); }, [active]);
  useEffect(() => {
    if (!expanded || project.kind === 'timeline') return;
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
  const Icon = project.kind === 'qqbot' ? Bot : project.kind === 'workspace' ? Compass : Boxes;
  return <SidebarMenuItem data-project-id={project.id}>
    <Collapsible open={expanded} onOpenChange={setExpanded}>
      <div className="group/project-heading relative flex items-center">
        <CollapsibleTrigger render={<SidebarMenuButton type="button"
          className={cn('project-select', project.kind !== 'timeline' &&
            'group-has-data-[sidebar=menu-action]/menu-item:pr-14 pointer-coarse:group-has-data-[sidebar=menu-action]/menu-item:pr-22')}
          isActive={active} title={project.name} disabled={deleting === project.id} />}>
          <Icon data-icon="inline-start" /><span>{project.name}</span>
        </CollapsibleTrigger>
        {project.kind !== 'timeline' ? <SidebarMenuAction type="button" aria-label={t('newProjectSession', { name: project.name })}
          title={t('newSession')} className="right-7 opacity-0 group-hover/project-heading:opacity-100 group-has-[:focus-visible]/project-heading:opacity-100 pointer-coarse:right-11 pointer-coarse:opacity-100"
          onClick={async () => { if (await onCreateSession(project.id)) { setExpanded(true); setOpenMobile(false); } }}>
          <MessageSquarePlus />
        </SidebarMenuAction> : null}
        <DropdownMenu>
          <DropdownMenuTrigger render={<SidebarMenuAction type="button" aria-label={t('projectActions', { name: project.name })} />}><MoreHorizontal /></DropdownMenuTrigger>
          <DropdownMenuContent align="end"><DropdownMenuGroup>
            <DropdownMenuItem onClick={() => void openSettings()}><Settings2 data-icon="inline-start" />{t('projectSettings')}</DropdownMenuItem>
            <DropdownMenuItem variant="destructive" disabled={!!deleting} onClick={() => void deleteProject()}><Trash2 data-icon="inline-start" />{t('deleteProject')}</DropdownMenuItem>
          </DropdownMenuGroup></DropdownMenuContent>
        </DropdownMenu>
      </div>
      {project.kind !== 'timeline' ? <CollapsibleContent>
        <SidebarMenuSub className="mr-0 translate-x-0 pr-0">
          {sessions.map((session) => {
            const title = session.title.trim() || t('newSession');
            const selected = (targetId ?? current?.session_id) === session.session_id;
            return <SidebarMenuSubItem key={session.session_id} className={cn('session-item', selected && 'selected')}>
              <SidebarMenuSubButton render={<button type="button" disabled={deleting === session.session_id} />}
                className="session-select w-full translate-x-0 pr-8 pointer-coarse:min-h-11 pointer-coarse:pr-11" isActive={selected} aria-current={selected ? 'page' : undefined} title={title}
                onClick={async () => { if (await onSelectSession(session.session_id, project.id)) setOpenMobile(false); }}><span>{title}</span></SidebarMenuSubButton>
              <DropdownMenu>
                <DropdownMenuTrigger render={<SidebarMenuAction type="button"
                  className="session-menu top-0.5 opacity-0 group-hover/menu-sub-item:opacity-100 group-has-[:focus-visible]/menu-sub-item:opacity-100 aria-expanded:opacity-100 pointer-coarse:opacity-100"
                  aria-label={t('sessionActions', { title })} />}><MoreHorizontal /></DropdownMenuTrigger>
                <DropdownMenuContent align="end"><DropdownMenuGroup>
                  <DropdownMenuItem variant="destructive" disabled={!!deleting} onClick={() => void deleteSession(session.session_id)}>
                    <Trash2 data-icon="inline-start" />{t('deleteSession')}
                  </DropdownMenuItem>
                </DropdownMenuGroup></DropdownMenuContent>
              </DropdownMenu>
            </SidebarMenuSubItem>;
          })}
          {(loading && !sessions.length) || error ? <SidebarMenuSubItem><ResourceLoading error={error} retry={() => setReload((n) => n + 1)} /></SidebarMenuSubItem> : null}
          {!loading && !error && !sessions.length ? <SidebarMenuSubItem><p className="model-empty px-2">{t(project.kind === 'qqbot' ? 'qq.emptyConversations' : 'noProjectSessions')}</p></SidebarMenuSubItem> : null}
        </SidebarMenuSub>
      </CollapsibleContent> : <CollapsibleContent><p className="model-empty px-2 py-2">{t('timelineCreationOnly')}</p></CollapsibleContent>}
    </Collapsible>
    {confirmation}
  </SidebarMenuItem>;
}
