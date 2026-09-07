import type { ReactNode } from 'react';
export type ModelTask = (task: () => Promise<unknown>, refresh?: boolean) => Promise<void>;
export type ModelFeedbackProps = {
  busy: boolean;
  run: ModelTask;
  feedback: ReactNode;
  setError: (message: string) => void;
};
