import { Module } from '@nestjs/common';
import { KbChatController } from './kb-chat.controller';
import { KbChatService } from './kb-chat.service';

@Module({
  imports: [],
  controllers: [KbChatController],
  providers: [KbChatService],
})
export class KbChatModule {}
