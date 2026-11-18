import React from 'react';
import { AppProvider, useApp } from './context/AppContext';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { DashboardView } from './components/dashboard/DashboardView';
import { ProcessingView } from './components/processing/ProcessingView';
import { ClipEditorView } from './components/editor/ClipEditorView';
import { ExportView } from './components/exports/ExportView';
import { ProjectsView } from './components/projects/ProjectsView';
import { SettingsView } from './components/settings/SettingsView';
import { NewProjectModal } from './components/dashboard/NewProjectModal';
import { Toast } from './components/common/Toast';

const MainContent: React.FC = () => {
  const { currentView, setCurrentView } = useApp();

  return (
    <div className="flex min-h-screen bg-[#0b0c10] text-slate-100 antialiased font-sans">
      <Sidebar />

      <div className="flex-1 flex flex-col min-w-0">
        <Header />

        <main className="flex-1 pb-16">
          {currentView === 'dashboard' && <DashboardView />}
          {currentView === 'create' && (
            <div className="p-8 max-w-4xl mx-auto">
              <DashboardView />
              <NewProjectModal
                isOpen={true}
                onClose={() => setCurrentView('dashboard')}
                defaultTab="local"
              />
            </div>
          )}
          {currentView === 'processing' && <ProcessingView />}
          {currentView === 'editor' && <ClipEditorView />}
          {currentView === 'exports' && <ExportView />}
          {currentView === 'projects' && <ProjectsView />}
          {currentView === 'settings' && <SettingsView />}
        </main>
      </div>

      <Toast />
    </div>
  );
};

export default function App() {
  return (
    <AppProvider>
      <MainContent />
    </AppProvider>
  );
}
