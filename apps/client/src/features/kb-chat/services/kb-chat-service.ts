import api from "@/lib/api-client.ts";

export interface KbChatRequest {
  query: string;
}

export interface KbSource {
  pageId: string;
  title: string;
  slugId: string;
  spaceSlug?: string;
  similarity: number;
  matchedText?: string;
}

export interface KbChatResponse {
  answer: string;
  sources: KbSource[];
}

export async function sendKbChatMessage(
  request: KbChatRequest,
): Promise<KbChatResponse> {
  const response = await api.post<KbChatResponse>("/kb-chat", request);
  return response.data;
}
