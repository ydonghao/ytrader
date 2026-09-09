import React, {HTMLAttributes, forwardRef, createContext, useContext, useState} from 'react';
import clsx from 'clsx';
import './Tabs.css';

interface TabsContextValue {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

const TabsContext = createContext<TabsContextValue | null>(null);

const useTabsContext = () => {
  const context = useContext(TabsContext);
  if (!context) {
    throw new Error('Tabs components must be used within a Tabs provider');
  }
  return context;
};

export interface TabsProps extends HTMLAttributes<HTMLDivElement> {
  defaultTab?: string;
  value?: string;
  onChange?: (tab: string) => void;
}

export const Tabs = forwardRef<HTMLDivElement, TabsProps>(
  ({children, className, defaultTab, value, onChange, ...props}, ref) => {
    const [internalTab, setInternalTab] = useState(defaultTab || '');
    const activeTab = value !== undefined ? value : internalTab;

    const setActiveTab = (tab: string) => {
      if (value === undefined) {
        setInternalTab(tab);
      }
      onChange?.(tab);
    };

    return (
      <TabsContext.Provider value={{activeTab, setActiveTab}}>
        <div ref={ref} className={clsx('tabs', className)} {...props}>
          {children}
        </div>
      </TabsContext.Provider>
    );
  }
);

Tabs.displayName = 'Tabs';

export interface TabListProps extends HTMLAttributes<HTMLDivElement> {}

export const TabList = forwardRef<HTMLDivElement, TabListProps>(
  ({children, className, ...props}, ref) => {
    return (
      <div ref={ref} className={clsx('tabs__list', className)} role="tablist" {...props}>
        {children}
      </div>
    );
  }
);

TabList.displayName = 'TabList';

export interface TabProps extends HTMLAttributes<HTMLButtonElement> {
  value: string;
  disabled?: boolean;
}

export const Tab = forwardRef<HTMLButtonElement, TabProps>(
  ({children, className, value, disabled = false, ...props}, ref) => {
    const {activeTab, setActiveTab} = useTabsContext();
    const isActive = activeTab === value;

    return (
      <button
        ref={ref}
        type="button"
        role="tab"
        className={clsx(
          'tabs__tab',
          {
            'tabs__tab--active': isActive,
            'tabs__tab--disabled': disabled,
          },
          className
        )}
        aria-selected={isActive}
        disabled={disabled}
        onClick={() => setActiveTab(value)}
        {...props}
      >
        {children}
      </button>
    );
  }
);

Tab.displayName = 'Tab';

export interface TabPanelProps extends HTMLAttributes<HTMLDivElement> {
  value: string;
}

export const TabPanel = forwardRef<HTMLDivElement, TabPanelProps>(
  ({children, className, value, ...props}, ref) => {
    const {activeTab} = useTabsContext();
    if (activeTab !== value) return null;

    return (
      <div
        ref={ref}
        className={clsx('tabs__panel', className)}
        role="tabpanel"
        {...props}
      >
        {children}
      </div>
    );
  }
);

TabPanel.displayName = 'TabPanel';
