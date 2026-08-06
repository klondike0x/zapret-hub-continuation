import { useAppState } from "./useBridgeState";
import { dict, type LocaleKey } from "@/locale/dict";
import type { Locale } from "@/bridge/types";

export function useLocale() {
  const state = useAppState();
  const locale: Locale = state?.ui.locale ?? "ru";
  const t = (key: LocaleKey) => dict[locale][key] ?? dict.en[key] ?? key;
  return { t, locale };
}

