"use client";
import { createContext, useContext } from "react";

export const VoiceCtx = createContext<{ open: (initialText?: string) => void }>({ open: () => {} });
export const useVoicePanel = () => useContext(VoiceCtx);
