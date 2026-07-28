import {
  Body,
  Controller,
  HttpCode,
  HttpStatus,
  Logger,
  Post,
  UseGuards,
} from '@nestjs/common';
import { KbChatService, KbChatResult } from './kb-chat.service';
import { KbChatDto } from './dto/kb-chat.dto';
import { JwtAuthGuard } from '../../common/guards/jwt-auth.guard';
import { AuthUser } from '../../common/decorators/auth-user.decorator';
import { User } from '@docmost/db/types/entity.types';

@UseGuards(JwtAuthGuard)
@Controller('kb-chat')
export class KbChatController {
  private readonly logger = new Logger(KbChatController.name);

  constructor(private readonly kbChatService: KbChatService) {}

  /**
   * POST /kb-chat
   * Accepts a natural-language question and returns a KB-grounded answer
   * with source references. Requires an authenticated Docmost session.
   */
  @HttpCode(HttpStatus.OK)
  @Post()
  async chat(
    @Body() dto: KbChatDto,
    @AuthUser() user: User,
  ): Promise<KbChatResult> {
    this.logger.log(`KB chat request from user=${user.id}: "${dto.query.slice(0, 80)}"`);
    return this.kbChatService.query(dto.query);
  }
}
