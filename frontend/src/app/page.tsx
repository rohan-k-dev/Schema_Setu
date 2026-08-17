"use client";

import React, { useState, useRef } from "react";
import { Send, Mic, Sparkles, AlertCircle, CheckCircle2, User, Sprout, MapPin } from "lucide-react";

interface Scheme {
  scheme_name: string;
  benefit: string;
  xai_explanation: string;
}

interface FarmerProfile {
  state?: string;
  district?: string;
  land_size_acres?: number;
  primary_crop?: string;
  annual_income?: number;
  category?: string;
  gender?: string;
}

interface Message {
  sender: "user" | "agent";
  text: string;
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([
    {
      sender: "agent",
      text: "Namaste! I am your Kisan Assistant. Tell me about your farming land, state, and the crop you grow so I can find government schemes for you.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [profile, setProfile] = useState<FarmerProfile | null>(null);
  const [schemes, setSchemes] = useState<Scheme[]>([]);

  // Refs for audio recording
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<BlobPart[]>([]);

  // Helper to play audio from the backend
  const playAudioResponse = async (textToSpeak: string) => {
    try {
      const response = await fetch("http://localhost:8000/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: textToSpeak, language_code: "hi-IN" }),
      });
      const data = await response.json();

      if (data.audio_base64) {
        const audio = new Audio(`data:audio/wav;base64,${data.audio_base64}`);
        audio.play();
      }
    } catch (error) {
      console.error("TTS Playback failed:", error);
    }
  };

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMsg = input;
    setInput("");
    setMessages((prev) => [...prev, { sender: "user", text: userMsg }]);
    setLoading(true);

    try {
      const response = await fetch("http://localhost:8000/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg, thread_id: "demo_farmer_1" }),
      });

      const data = await response.json();

      if (data.current_profile) {
        setProfile(data.current_profile);
      }

      if (data.status === "asking_question") {
        setMessages((prev) => [...prev, { sender: "agent", text: data.reply }]);
        playAudioResponse(data.reply);
      } else if (data.status === "schemes_found") {
        setSchemes(data.schemes);
        const summary = `I found ${data.schemes.length} schemes tailored for you!`;
        setMessages((prev) => [...prev, { sender: "agent", text: summary }]);
        playAudioResponse(summary);
      } else {
        setMessages((prev) => [
          ...prev,
          { sender: "agent", text: "Sorry, I had trouble processing that. Could you try again?" },
        ]);
      }
    } catch (error) {
      console.error("API Error:", error);
      setMessages((prev) => [
        ...prev,
        { sender: "agent", text: "Unable to connect to the server. Make sure Docker is running!" },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const sendAudioToBackend = async (audioBlob: Blob) => {
    setLoading(true);
    setMessages((prev) => [...prev, { sender: "user", text: "🎙️ (Voice Audio Sent)" }]);

    const formData = new FormData();
    formData.append("file", audioBlob, "recording.wav");
    formData.append("thread_id", "demo_farmer_1");

    try {
      const response = await fetch("http://localhost:8000/voice", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (data.current_profile) setProfile(data.current_profile);

      if (data.user_transcript) {
        setMessages((prev) => {
          const newMsgs = [...prev];
          newMsgs[newMsgs.length - 1].text = `🎙️ "${data.user_transcript}"`;
          return newMsgs;
        });
      }

      if (data.status === "asking_question") {
        setMessages((prev) => [...prev, { sender: "agent", text: data.reply }]);
        playAudioResponse(data.reply);
      } else if (data.status === "schemes_found") {
        setSchemes(data.schemes);
        const summary = `I found ${data.schemes.length} schemes tailored for you!`;
        setMessages((prev) => [...prev, { sender: "agent", text: summary }]);
        playAudioResponse(summary);
      }
    } catch (error) {
      console.error("Voice API Error:", error);
      setMessages((prev) => [...prev, { sender: "agent", text: "Failed to process voice." }]);
    } finally {
      setLoading(false);
    }
  };

  const handleVoiceToggle = async () => {
    if (isRecording) {
      // Stop Recording
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
    } else {
      // Start Recording
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mediaRecorder = new MediaRecorder(stream);
        mediaRecorderRef.current = mediaRecorder;
        audioChunksRef.current = [];

        mediaRecorder.ondataavailable = (event) => {
          if (event.data.size > 0) {
            audioChunksRef.current.push(event.data);
          }
        };

        mediaRecorder.onstop = async () => {
          const audioBlob = new Blob(audioChunksRef.current, { type: "audio/wav" });
          await sendAudioToBackend(audioBlob);
          stream.getTracks().forEach((track) => track.stop());
        };

        mediaRecorder.start();
        setIsRecording(true);
      } catch (err) {
        console.error("Microphone access denied:", err);
        alert("Please allow microphone access to use the voice feature.");
      }
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans">
      {/* Navbar */}
      <header className="bg-emerald-800 text-white shadow-md py-4 px-6 flex justify-between items-center">
        <div className="flex items-center space-x-3">
          <Sprout className="h-8 w-8 text-emerald-400" />
          <div>
            <h1 className="text-xl font-bold tracking-wide">Rural Edge AI</h1>
            <p className="text-xs text-emerald-200">Decentralized Scheme Recommendation & Empowerment</p>
          </div>
        </div>
        <div className="flex items-center space-x-2 bg-emerald-900 px-3 py-1.5 rounded-full text-sm">
          <span className="h-2 w-2 rounded-full bg-green-400 animate-pulse"></span>
          <span>Groq LLaMA 3.3 Active</span>
        </div>
      </header>

      {/* Main Layout */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 md:p-6 grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Left 2 Columns: Chat & Voice Interaction */}
        <div className="lg:col-span-2 bg-white rounded-xl shadow-sm border border-slate-200 flex flex-col overflow-hidden h-[750px]">
          <div className="p-4 bg-slate-100 border-b border-slate-200 font-semibold text-slate-700 flex items-center justify-between">
            <span>Kisan Recommendation Assistant</span>
            <span className="text-xs text-slate-500">Multilingual Voice & Text Enabled</span>
          </div>

          {/* Messages Area */}
          <div className="flex-1 p-4 overflow-y-auto space-y-4">
            {messages.map((msg, idx) => (
              <div
                key={idx}
                className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${msg.sender === "user"
                      ? "bg-emerald-600 text-white rounded-br-none"
                      : "bg-slate-100 text-slate-800 border border-slate-200 rounded-bl-none"
                    }`}
                >
                  {msg.text}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-slate-100 border border-slate-200 rounded-2xl px-4 py-3 text-sm text-slate-500 flex items-center space-x-2">
                  <Sparkles className="h-4 w-4 text-emerald-600 animate-spin" />
                  <span>Analyzing eligibility and querying scheme databases...</span>
                </div>
              </div>
            )}
          </div>

          {/* Input Bar */}
          <div className="p-4 border-t border-slate-200 bg-white flex items-center space-x-2">
            <button
              onClick={handleVoiceToggle}
              className={`p-3 rounded-xl flex items-center justify-center transition-colors ${isRecording
                  ? "bg-red-500 text-white animate-pulse shadow-[0_0_15px_rgba(239,68,68,0.5)]"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              title="Record Voice (Sarvam AI)"
            >
              <Mic className="h-5 w-5" />
            </button>

            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
              placeholder="e.g., I am from Karnataka, growing maize on 2.5 acres..."
              className="flex-1 bg-slate-100 border-0 focus:ring-2 focus:ring-emerald-600 rounded-xl px-4 py-3 text-sm text-slate-800 placeholder-slate-400 outline-none"
            />

            <button
              onClick={handleSend}
              disabled={loading || (!input.trim() && !isRecording)}
              className="bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white p-3 rounded-xl flex items-center justify-center transition-colors"
            >
              <Send className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Right 1 Column: Extracted Profile & Scheme Cards */}
        <div className="space-y-6 flex flex-col h-[750px] overflow-y-auto pr-1">

          {/* Active Profile Matrix */}
          <div className="bg-white p-5 rounded-xl shadow-sm border border-slate-200">
            <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3 flex items-center">
              <User className="h-4 w-4 mr-2 text-emerald-600" /> Extracted Profile Matrix
            </h2>
            {profile ? (
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-100">
                  <span className="text-xs text-slate-400 block">State</span>
                  <span className="font-medium text-slate-700 flex items-center mt-0.5">
                    <MapPin className="h-3.5 w-3.5 mr-1 text-slate-400" />
                    {profile.state || "Not set"}
                  </span>
                </div>
                <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-100">
                  <span className="text-xs text-slate-400 block">Land Size</span>
                  <span className="font-medium text-slate-700 mt-0.5 block">
                    {profile.land_size_acres ? `${profile.land_size_acres} Acres` : "Not set"}
                  </span>
                </div>
                <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-100 col-span-2">
                  <span className="text-xs text-slate-400 block">Primary Crop</span>
                  <span className="font-medium text-slate-700 mt-0.5 block">
                    {profile.primary_crop || "Not set"}
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-400 italic">No profile data extracted yet. Start chatting to populate fields.</p>
            )}
          </div>

          {/* Recommended Schemes Area */}
          <div className="bg-white p-5 rounded-xl shadow-sm border border-slate-200 flex-1 flex flex-col">
            <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3 flex items-center">
              <CheckCircle2 className="h-4 w-4 mr-2 text-emerald-600" /> Personalized Schemes ({schemes.length})
            </h2>

            {schemes.length > 0 ? (
              <div className="space-y-4 overflow-y-auto flex-1 pr-1">
                {schemes.map((scheme, idx) => (
                  <div key={idx} className="border border-emerald-100 bg-emerald-50/30 rounded-xl p-4 space-y-2">
                    <h3 className="font-bold text-slate-800 text-sm leading-snug">{scheme.scheme_name}</h3>
                    <p className="text-xs text-slate-600 bg-white p-2 rounded-lg border border-slate-100">
                      <span className="font-semibold text-slate-700">Benefit: </span>{scheme.benefit}
                    </p>
                    <div className="bg-emerald-100/50 p-2.5 rounded-lg border border-emerald-200/60">
                      <span className="text-[11px] font-bold text-emerald-800 uppercase tracking-wider block mb-0.5 flex items-center">
                        <Sparkles className="h-3 w-3 mr-1 text-emerald-700" /> Why you are eligible (XAI)
                      </span>
                      <p className="text-xs text-emerald-950 leading-relaxed font-medium">
                        {scheme.xai_explanation}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center text-center p-6 border-2 border-dashed border-slate-200 rounded-xl">
                <AlertCircle className="h-8 w-8 text-slate-300 mb-2" />
                <p className="text-xs text-slate-500 max-w-[200px]">
                  Provide your critical details (State, Land, Crop) to generate explainable recommendations.
                </p>
              </div>
            )}
          </div>

        </div>
      </main>
    </div>
  );
}