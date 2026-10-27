export type FarkleHost = {
  brand: string;
  tableUrl: string;
  backUrl: string | null;
  storagePrefix: string;
};

// The standalone build selects its own host module at the build boundary.
export const farkleHost: FarkleHost = {
  brand: 'Cogita',
  tableUrl: '/playground/farkle',
  backUrl: '/playground',
  storagePrefix: 'cogita.farkle',
};
