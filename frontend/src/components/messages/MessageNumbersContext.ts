import { createContext } from 'react';

export const MessageNumbersContext = createContext<ReadonlyMap<string, number>>(new Map());
