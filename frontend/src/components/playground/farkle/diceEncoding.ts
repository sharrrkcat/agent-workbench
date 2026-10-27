import type { DieType } from './dice';

// Fixed storage identities shared with history format 1. Never use display/catalog order.
const diceTypesByCode: readonly DieType[] = ['normal', 'even', 'odd', 'devil', 'weighted', 'lucky', 'unlucky',
  'favourable', 'pie', 'misfortune', 'monk', 'strip', 'unbalanced', 'shrinking', 'painted', 'heavenly',
  'grimy', 'lu', 'ci', 'fer', 'aranka', 'merchant'];

export const encodeDie = (type: DieType) => String.fromCharCode(97 + diceTypesByCode.indexOf(type));
export const decodeDie = (code: string): DieType => diceTypesByCode[code.charCodeAt(0) - 97];
export const isDiceCode = (value: unknown): value is string => typeof value === 'string' && value.length === 1 && /^[a-v]$/.test(value);
export const isEncodedDice = (value: unknown): value is string => typeof value === 'string' && value.length === 6 && /^[a-v]{6}$/.test(value);
export const encodeDice = (dice: readonly DieType[]) => dice.map(encodeDie).join('');
export const decodeDice = (code: string): DieType[] => [...code].map(decodeDie);
