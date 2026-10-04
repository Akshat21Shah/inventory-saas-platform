/** App-wide signals between the API layer and the screens. */
type Listener = () => void;

function channel() {
  const listeners = new Set<Listener>();
  return {
    emit: () => listeners.forEach((listener) => listener()),
    listen: (listener: Listener) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  };
}

/** The session ended (the refresh failed): back to sign-in. */
export const sessionEnded = channel();
/** The API refused this app version (426 APP_UPDATE_REQUIRED): show the update screen. */
export const updateRequired = channel();
