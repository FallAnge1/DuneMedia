export interface AppEnv {
  Bindings: Env;
  Variables: {
    uploader: { id: number; name: string };
  };
}
