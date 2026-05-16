import type { ReactNode } from 'react';
import type { CommandButtonsBlock, CommandButtonsMessagePart } from '../../../types';

export function CommandButtonsPartRenderer({
  part,
  renderCommandButtons,
}: {
  part: CommandButtonsMessagePart;
  renderCommandButtons: (block: CommandButtonsBlock) => ReactNode;
}) {
  return <>{renderCommandButtons({ type: 'command_buttons', buttons: part.buttons })}</>;
}
