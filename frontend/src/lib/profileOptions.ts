/**
 * Choices for the saved-profile fields — shared by the profile page and the
 * dashboard's inline "fix missing details" editors, so both send the same values.
 */

export const INDIAN_STATES = [
  "Andhra Pradesh","Arunachal Pradesh","Assam","Bihar","Chhattisgarh","Goa",
  "Gujarat","Haryana","Himachal Pradesh","Jharkhand","Karnataka","Kerala",
  "Madhya Pradesh","Maharashtra","Manipur","Meghalaya","Mizoram","Nagaland",
  "Odisha","Punjab","Rajasthan","Sikkim","Tamil Nadu","Telangana","Tripura",
  "Uttar Pradesh","Uttarakhand","West Bengal","Andaman and Nicobar Islands",
  "Chandigarh","Dadra and Nagar Haveli and Daman and Diu","Delhi",
  "Jammu and Kashmir","Ladakh","Lakshadweep","Puducherry",
];

export const CROPS = [
  "rice","wheat","maize","ragi","groundnut","mustard","soybean","cotton",
  "sugarcane","sorghum","pearl millet","tur","chickpea","lentil","mung bean",
  "onion","potato","tomato","banana","mango","coconut","jute","tea","coffee",
];

export const LAND_UNITS: { value: string; label: string }[] = [
  { value: "acre", label: "Acres" },
  { value: "hectare", label: "Hectares" },
  { value: "guntha", label: "Guntha (40 = 1 acre)" },
  { value: "cent", label: "Cents (100 = 1 acre)" },
];

export const INCOME_RANGES: { value: string; label: string }[] = [
  { value: "below_1_lakh", label: "Below ₹1 lakh" },
  { value: "1_to_2.5_lakh", label: "₹1 – 2.5 lakh" },
  { value: "2.5_to_5_lakh", label: "₹2.5 – 5 lakh" },
  { value: "5_to_10_lakh", label: "₹5 – 10 lakh" },
  { value: "above_10_lakh", label: "Above ₹10 lakh" },
];

export const OCCUPATIONS = ["farmer", "agricultural labourer", "tenant farmer", "livestock farmer", "fisher", "other"];

export const GENDERS: { value: string; label: string }[] = [
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
  { value: "other", label: "Other" },
];

export const CATEGORIES = ["General", "OBC", "SC", "ST", "EWS"];

export const RESIDENCES: { value: string; label: string }[] = [
  { value: "rural", label: "Village (rural)" },
  { value: "urban", label: "Town / city (urban)" },
];
