"use client";

import React from "react";
import type { FarmerProfile } from "@/lib/types";
import { User, MapPin } from "lucide-react";

interface ProfilePanelProps {
  profile: FarmerProfile | null;
}

export default function ProfilePanel({ profile }: ProfilePanelProps) {
  return (
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
              {profile.land_size_acres != null ? `${profile.land_size_acres} Acres` : "Not set"}
            </span>
          </div>
          <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-100 col-span-2">
            <span className="text-xs text-slate-400 block">Primary Crop</span>
            <span className="font-medium text-slate-700 mt-0.5 block">
              {profile.primary_crop || "Not set"}
            </span>
          </div>
          {profile.occupation && (
            <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-100">
              <span className="text-xs text-slate-400 block">Occupation</span>
              <span className="font-medium text-slate-700 mt-0.5 block capitalize">{profile.occupation}</span>
            </div>
          )}
          {profile.age != null && (
            <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-100">
              <span className="text-xs text-slate-400 block">Age</span>
              <span className="font-medium text-slate-700 mt-0.5 block">{profile.age}</span>
            </div>
          )}
        </div>
      ) : (
        <p className="text-xs text-slate-400 italic">
          No profile data extracted yet. Start chatting to populate fields.
        </p>
      )}
    </div>
  );
}
