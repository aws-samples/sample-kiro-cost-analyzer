import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

interface SplitPanelContextValue {
  splitPanelContent: ReactNode | null;
  splitPanelOpen: boolean;
  setSplitPanelContent: (content: ReactNode | null) => void;
  setSplitPanelOpen: (open: boolean) => void;
  closeSplitPanel: () => void;
}

const SplitPanelContext = createContext<SplitPanelContextValue>({
  splitPanelContent: null,
  splitPanelOpen: false,
  setSplitPanelContent: () => {},
  setSplitPanelOpen: () => {},
  closeSplitPanel: () => {},
});

export function SplitPanelProvider({ children }: { children: ReactNode }) {
  const [splitPanelContent, setSplitPanelContent] = useState<ReactNode | null>(null);
  const [splitPanelOpen, setSplitPanelOpen] = useState(false);

  const closeSplitPanel = useCallback(() => {
    setSplitPanelOpen(false);
    setSplitPanelContent(null);
  }, []);

  return (
    <SplitPanelContext.Provider
      value={{
        splitPanelContent,
        splitPanelOpen,
        setSplitPanelContent,
        setSplitPanelOpen,
        closeSplitPanel,
      }}
    >
      {children}
    </SplitPanelContext.Provider>
  );
}

export function useSplitPanel() {
  return useContext(SplitPanelContext);
}
