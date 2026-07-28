import { IsString, MaxLength, MinLength } from 'class-validator';

export class KbChatDto {
  @IsString()
  @MinLength(1)
  @MaxLength(500)
  query: string;
}
