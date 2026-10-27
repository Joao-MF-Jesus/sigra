import React, { createContext, useContext } from "react";

export const SessionContext = createContext({ user: null });
export function useSession() { return useContext(SessionContext); }
