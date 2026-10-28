"use client";

import React, { useEffect, useState } from "react";
import { Globe } from "lucide-react";
import { fetchLanguages, type LanguageInfo } from "@/lib/api";

/**
 * Default language list used when API is unavailable.
 */
const FALLBACK_LANGUAGES: LanguageInfo[] = [
  { code: "en", name: "English", english_name: "English", has_voice: true, has_tts: true },
  { code: "hi", name: "हिन्दी", english_name: "Hindi", has_voice: true, has_tts: true },
  { code: "kn", name: "ಕನ್ನಡ", english_name: "Kannada", has_voice: true, has_tts: true },
  { code: "ta", name: "தமிழ்", english_name: "Tamil", has_voice: true, has_tts: true },
  { code: "te", name: "తెలుగు", english_name: "Telugu", has_voice: true, has_tts: true },
  { code: "mr", name: "मराठी", english_name: "Marathi", has_voice: true, has_tts: true },
  { code: "bn", name: "বাংলা", english_name: "Bengali", has_voice: true, has_tts: true },
  { code: "gu", name: "ગુજરાતી", english_name: "Gujarati", has_voice: true, has_tts: true },
  { code: "od", name: "ଓଡ଼ିଆ", english_name: "Odia", has_voice: true, has_tts: true },
];

interface LanguageSelectorProps {
  selectedLanguage: string;
  onLanguageChange: (code: string) => void;
}

/**
 * Language selector — clearly visible, mobile friendly (§11).
 * Shows native names, no technical codes (§11).
 */
export default function LanguageSelector({
  selectedLanguage,
  onLanguageChange,
}: LanguageSelectorProps) {
  const [languages, setLanguages] = useState<LanguageInfo[]>(FALLBACK_LANGUAGES);
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    fetchLanguages().then((langs) => {
      if (langs.length > 0) setLanguages(langs);
    });
  }, []);

  const selected = languages.find((l) => l.code === selectedLanguage) || languages[0];

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/10 hover:bg-white/20 transition-colors text-white text-sm font-medium min-w-[44px] min-h-[44px] focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
        aria-label="Select language"
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        id="language-selector"
      >
        <Globe className="h-4 w-4" />
        <span className="hidden sm:inline">{selected.name}</span>
        <span className="sm:hidden">{selected.code.toUpperCase()}</span>
      </button>

      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
            aria-hidden="true"
          />
          {/* Dropdown */}
          <div
            className="absolute right-0 top-full mt-1 bg-white rounded-xl shadow-xl border border-slate-200 py-1 z-50 min-w-[200px] max-h-[320px] overflow-y-auto"
            role="listbox"
            aria-labelledby="language-selector"
          >
            {languages.map((lang) => (
              <button
                key={lang.code}
                onClick={() => {
                  onLanguageChange(lang.code);
                  setIsOpen(false);
                }}
                className={`w-full text-left px-4 py-3 text-sm flex items-center justify-between hover:bg-slate-50 transition-colors min-h-[44px] focus:outline-none focus-visible:bg-emerald-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600 ${
                  lang.code === selectedLanguage
                    ? "bg-emerald-50 text-emerald-700 font-semibold"
                    : "text-slate-700"
                }`}
                role="option"
                aria-selected={lang.code === selectedLanguage}
              >
                <div>
                  <span className="block font-medium">{lang.name}</span>
                  <span className="text-xs text-slate-400">{lang.english_name}</span>
                </div>
                {lang.code === selectedLanguage && (
                  <span className="text-emerald-600 text-lg">✓</span>
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
