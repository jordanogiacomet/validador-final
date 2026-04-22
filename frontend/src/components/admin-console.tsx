"use client";

import React from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";

import {
  createAdminTenant,
  createOperatorAccount,
  createOperatorInvitation,
  disableAdminTenant,
  disableOperatorAccount,
  formatApiErrorMessage,
  getTenantValidationProfile,
  listAdminTenants,
  listOperators,
  publishTenantValidationProfileDraft,
  reactivateAdminTenant,
  resetOperatorAccountPassword,
  rollbackTenantValidationProfile,
  saveTenantValidationProfileDraft,
  updateAdminTenant,
} from "@/lib/api";
import type {
  OperatorInvitationResponse,
  OperatorResponse,
  OperatorRole,
  TenantAdminResponse,
  TenantValidationProfileData,
  TenantValidationProfileResponse,
} from "@/lib/types";

type AdminSection = "operators" | "tenants" | "profiles";
type NoticeKind = "success" | "error";

interface AdminConsoleProps {
  role: OperatorRole;
  sessionTenantId: string;
  onClose: () => void;
}

interface NoticeState {
  kind: NoticeKind;
  message: string;
}

interface CreateOperatorFormState {
  username: string;
  password: string;
  role: OperatorRole;
  requirePasswordChange: boolean;
}

interface InviteOperatorFormState {
  username: string;
  role: OperatorRole;
  expiresInHours: string;
}

interface ResetPasswordFormState {
  password: string;
  requirePasswordChange: boolean;
}

interface CreateTenantFormState {
  tenantId: string;
  displayName: string;
  aliases: string;
}

interface TenantDraftState {
  displayName: string;
  aliases: string;
}

const INITIAL_RESET_PASSWORD_FORM_STATE: ResetPasswordFormState = {
  password: "",
  requirePasswordChange: true,
};

const TENANT_ID_PATTERN = /^[a-z0-9][a-z0-9._-]{1,62}[a-z0-9]$/;
const USERNAME_PATTERN = /^[A-Za-z0-9._@-]+$/;

function isPlatformAdmin(role: OperatorRole): boolean {
  return role === "platform_admin";
}

function getRoleLabel(role: OperatorRole | undefined): string {
  switch (role) {
    case "platform_admin":
      return "Administrador global";
    case "tenant_admin":
      return "Administrador da empresa";
    default:
      return "Operador";
  }
}

function getTenantSourceLabel(source: TenantAdminResponse["source"]): string {
  return source === "runtime" ? "Criado na aplicação" : "Configurado em arquivo";
}

function getProfileSourceLabel(source: TenantValidationProfileResponse["source"]): string {
  return source === "published" ? "Versão publicada" : "Fallback em arquivo";
}

function getAllowedRoleOptions(role: OperatorRole): OperatorRole[] {
  return isPlatformAdmin(role)
    ? ["operator", "tenant_admin", "platform_admin"]
    : ["operator", "tenant_admin"];
}

function buildOperatorFormState(): CreateOperatorFormState {
  return {
    username: "",
    password: "",
    role: "operator",
    requirePasswordChange: true,
  };
}

function buildInviteFormState(): InviteOperatorFormState {
  return {
    username: "",
    role: "operator",
    expiresInHours: "48",
  };
}

function parseAliases(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatAliases(aliases: string[]): string {
  return aliases.join(", ");
}

function formatProfileJson(profile: TenantValidationProfileData): string {
  return JSON.stringify(profile, null, 2);
}

function parseProfileJson(value: string): TenantValidationProfileData {
  return JSON.parse(value) as TenantValidationProfileData;
}

function buildTenantDrafts(
  tenants: TenantAdminResponse[],
): Record<string, TenantDraftState> {
  return Object.fromEntries(
    tenants.map((tenant) => [
      tenant.tenant_id,
      {
        displayName: tenant.display_name,
        aliases: formatAliases(tenant.aliases),
      },
    ]),
  );
}

function sortOperators(operators: OperatorResponse[]): OperatorResponse[] {
  return [...operators].sort((left, right) =>
    left.username.localeCompare(right.username, "pt-BR", { sensitivity: "base" }),
  );
}

function getOperatorStatusSummary(operator: OperatorResponse): string {
  if (operator.disabled) {
    return "Conta desabilitada";
  }

  if (operator.must_change_password) {
    return "Senha provisória ativa";
  }

  return "Conta ativa";
}

export function AdminConsole({
  role,
  sessionTenantId,
  onClose,
}: AdminConsoleProps) {
  const [activeSection, setActiveSection] = useState<AdminSection>("operators");
  const [tenants, setTenants] = useState<TenantAdminResponse[]>([]);
  const [isTenantsLoading, setIsTenantsLoading] = useState(isPlatformAdmin(role));
  const [tenantLoadError, setTenantLoadError] = useState<string | null>(null);
  const [tenantRefreshToken, setTenantRefreshToken] = useState(0);
  const [selectedOperatorTenantId, setSelectedOperatorTenantId] =
    useState(sessionTenantId);
  const [operators, setOperators] = useState<OperatorResponse[]>([]);
  const [isOperatorsLoading, setIsOperatorsLoading] = useState(false);
  const [operatorLoadError, setOperatorLoadError] = useState<string | null>(null);
  const [operatorRefreshToken, setOperatorRefreshToken] = useState(0);
  const [operatorNotice, setOperatorNotice] = useState<NoticeState | null>(null);
  const [tenantNotice, setTenantNotice] = useState<NoticeState | null>(null);
  const [createOperatorValues, setCreateOperatorValues] = useState(
    buildOperatorFormState(),
  );
  const [inviteOperatorValues, setInviteOperatorValues] = useState(
    buildInviteFormState(),
  );
  const [issuedInvitation, setIssuedInvitation] =
    useState<OperatorInvitationResponse | null>(null);
  const [resetTargetOperatorId, setResetTargetOperatorId] = useState<string | null>(null);
  const [resetPasswordValues, setResetPasswordValues] = useState<ResetPasswordFormState>(
    INITIAL_RESET_PASSWORD_FORM_STATE,
  );
  const [tenantDrafts, setTenantDrafts] = useState<Record<string, TenantDraftState>>({});
  const [createTenantValues, setCreateTenantValues] = useState<CreateTenantFormState>({
    tenantId: "",
    displayName: "",
    aliases: "",
  });
  const [selectedProfileTenantId, setSelectedProfileTenantId] =
    useState(sessionTenantId);
  const [profileState, setProfileState] =
    useState<TenantValidationProfileResponse | null>(null);
  const [profileJson, setProfileJson] = useState("");
  const [profileLoadError, setProfileLoadError] = useState<string | null>(null);
  const [profileNotice, setProfileNotice] = useState<NoticeState | null>(null);
  const [isProfileLoading, setIsProfileLoading] = useState(false);
  const [pendingProfileAction, setPendingProfileAction] = useState<string | null>(null);
  const [isCreatingOperator, setIsCreatingOperator] = useState(false);
  const [isInvitingOperator, setIsInvitingOperator] = useState(false);
  const [pendingOperatorAction, setPendingOperatorAction] = useState<string | null>(null);
  const [isCreatingTenant, setIsCreatingTenant] = useState(false);
  const [pendingTenantAction, setPendingTenantAction] = useState<string | null>(null);

  const operatorTenantOptions = useMemo(() => {
    if (!isPlatformAdmin(role)) {
      return [];
    }

    return tenants
      .filter((tenant) => !tenant.disabled)
      .sort((left, right) =>
        left.display_name.localeCompare(right.display_name, "pt-BR", {
          sensitivity: "base",
        }),
      );
  }, [role, tenants]);

  const profileTenantOptions = useMemo(() => {
    if (!isPlatformAdmin(role)) {
      return [];
    }

    return [...tenants].sort((left, right) =>
      left.display_name.localeCompare(right.display_name, "pt-BR", {
        sensitivity: "base",
      }),
    );
  }, [role, tenants]);

  const selectedOperatorTenant =
    tenants.find((tenant) => tenant.tenant_id === selectedOperatorTenantId) || null;

  useEffect(() => {
    if (!isPlatformAdmin(role)) {
      setTenants([]);
      setTenantDrafts({});
      setTenantLoadError(null);
      setIsTenantsLoading(false);
      setSelectedOperatorTenantId(sessionTenantId);
      setSelectedProfileTenantId(sessionTenantId);
      return;
    }

    let isCancelled = false;

    async function loadTenants() {
      setIsTenantsLoading(true);
      setTenantLoadError(null);

      try {
        const nextTenants = await listAdminTenants();
        if (isCancelled) {
          return;
        }

        setTenants(nextTenants);
        setTenantDrafts(buildTenantDrafts(nextTenants));
        setSelectedOperatorTenantId((currentTenantId) => {
          const nextOptions = nextTenants.filter((tenant) => !tenant.disabled);
          const preferredTenant =
            nextOptions.find((tenant) => tenant.tenant_id === currentTenantId) ||
            nextOptions.find((tenant) => tenant.tenant_id === sessionTenantId) ||
            nextOptions[0];
          return preferredTenant?.tenant_id || currentTenantId;
        });
        setSelectedProfileTenantId((currentTenantId) => {
          const preferredTenant =
            nextTenants.find((tenant) => tenant.tenant_id === currentTenantId) ||
            nextTenants.find((tenant) => tenant.tenant_id === sessionTenantId) ||
            nextTenants[0];
          return preferredTenant?.tenant_id || currentTenantId;
        });
      } catch (error) {
        if (isCancelled) {
          return;
        }

        setTenantLoadError(
          formatApiErrorMessage(error, "Não foi possível carregar a área de empresas."),
        );
      } finally {
        if (!isCancelled) {
          setIsTenantsLoading(false);
        }
      }
    }

    void loadTenants();
    return () => {
      isCancelled = true;
    };
  }, [role, sessionTenantId, tenantRefreshToken]);

  useEffect(() => {
    let isCancelled = false;

    async function loadOperatorsForTenant() {
      if (!selectedOperatorTenantId) {
        setOperators([]);
        setOperatorLoadError(null);
        setIsOperatorsLoading(false);
        return;
      }

      setIsOperatorsLoading(true);
      setOperatorLoadError(null);

      try {
        const payload = await listOperators(selectedOperatorTenantId);
        if (isCancelled) {
          return;
        }

        setOperators(sortOperators(payload));
      } catch (error) {
        if (isCancelled) {
          return;
        }

        setOperators([]);
        setOperatorLoadError(
          formatApiErrorMessage(error, "Não foi possível carregar os usuários da empresa."),
        );
      } finally {
        if (!isCancelled) {
          setIsOperatorsLoading(false);
        }
      }
    }

    void loadOperatorsForTenant();
    return () => {
      isCancelled = true;
    };
  }, [operatorRefreshToken, selectedOperatorTenantId]);

  useEffect(() => {
    setResetTargetOperatorId(null);
    setResetPasswordValues(INITIAL_RESET_PASSWORD_FORM_STATE);
    setIssuedInvitation(null);
    setOperatorNotice(null);
  }, [selectedOperatorTenantId]);

  useEffect(() => {
    if (activeSection !== "profiles") {
      return;
    }

    const tenantId = selectedProfileTenantId || sessionTenantId;
    if (!tenantId) {
      setProfileState(null);
      setProfileJson("");
      setProfileLoadError(null);
      return;
    }

    let isCancelled = false;

    async function loadProfile() {
      setIsProfileLoading(true);
      setProfileLoadError(null);

      try {
        const payload = await getTenantValidationProfile(tenantId);
        if (isCancelled) {
          return;
        }

        setProfileState(payload);
        setProfileJson(formatProfileJson(payload.draft?.profile || payload.current_profile));
      } catch (error) {
        if (isCancelled) {
          return;
        }

        setProfileState(null);
        setProfileJson("");
        setProfileLoadError(
          formatApiErrorMessage(error, "Não foi possível carregar o perfil de validação."),
        );
      } finally {
        if (!isCancelled) {
          setIsProfileLoading(false);
        }
      }
    }

    void loadProfile();
    return () => {
      isCancelled = true;
    };
  }, [activeSection, selectedProfileTenantId, sessionTenantId]);

  useEffect(() => {
    setProfileNotice(null);
    setProfileLoadError(null);
  }, [selectedProfileTenantId]);

  function handleCreateOperatorFieldChange(
    field: keyof CreateOperatorFormState,
  ): (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => void {
    return (event) => {
      const target = event.target;
      const nextValue =
        target instanceof HTMLInputElement && target.type === "checkbox"
          ? target.checked
          : target.value;
      setCreateOperatorValues((currentValue) => ({
        ...currentValue,
        [field]: nextValue,
      }));
      setOperatorNotice(null);
    };
  }

  function handleInviteFieldChange(
    field: keyof InviteOperatorFormState,
  ): (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => void {
    return (event) => {
      setInviteOperatorValues((currentValue) => ({
        ...currentValue,
        [field]: event.target.value,
      }));
      setOperatorNotice(null);
      setIssuedInvitation(null);
    };
  }

  function handleResetPasswordFieldChange(
    field: keyof ResetPasswordFormState,
  ): (event: ChangeEvent<HTMLInputElement>) => void {
    return (event) => {
      const target = event.target;
      const nextValue = target.type === "checkbox" ? target.checked : target.value;
      setResetPasswordValues((currentValue) => ({
        ...currentValue,
        [field]: nextValue,
      }));
      setOperatorNotice(null);
    };
  }

  function handleCreateTenantFieldChange(
    field: keyof CreateTenantFormState,
  ): (event: ChangeEvent<HTMLInputElement>) => void {
    return (event) => {
      setCreateTenantValues((currentValue) => ({
        ...currentValue,
        [field]: event.target.value,
      }));
      setTenantNotice(null);
    };
  }

  function handleTenantDraftChange(
    tenantId: string,
    field: keyof TenantDraftState,
  ): (event: ChangeEvent<HTMLInputElement>) => void {
    return (event) => {
      setTenantDrafts((currentValue) => ({
        ...currentValue,
        [tenantId]: {
          ...(currentValue[tenantId] || { displayName: "", aliases: "" }),
          [field]: event.target.value,
        },
      }));
      setTenantNotice(null);
    };
  }

  async function handleCreateOperator(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const username = createOperatorValues.username.trim();
    const password = createOperatorValues.password;

    if (!selectedOperatorTenantId) {
      setOperatorNotice({
        kind: "error",
        message: "Selecione uma empresa antes de criar o usuário.",
      });
      return;
    }

    if (!username || !USERNAME_PATTERN.test(username)) {
      setOperatorNotice({
        kind: "error",
        message: "Use um usuário com letras, números, ponto, arroba, hífen ou underscore.",
      });
      return;
    }

    if (!password.trim()) {
      setOperatorNotice({
        kind: "error",
        message: "Informe a senha temporária do novo usuário.",
      });
      return;
    }

    setIsCreatingOperator(true);
    setOperatorNotice(null);
    setIssuedInvitation(null);

    try {
      const operator = await createOperatorAccount({
        tenantId: selectedOperatorTenantId,
        username,
        password,
        role: createOperatorValues.role,
        requirePasswordChange: createOperatorValues.requirePasswordChange,
      });

      setCreateOperatorValues(buildOperatorFormState());
      setOperatorNotice({
        kind: "success",
        message: operator.must_change_password
          ? `Usuário ${operator.username} criado com senha temporária e troca obrigatória no primeiro acesso.`
          : `Usuário ${operator.username} criado e liberado para acesso.`,
      });
      setOperatorRefreshToken((currentValue) => currentValue + 1);
    } catch (error) {
      setOperatorNotice({
        kind: "error",
        message: formatApiErrorMessage(error, "Não foi possível criar o usuário."),
      });
    } finally {
      setIsCreatingOperator(false);
    }
  }

  async function handleInviteOperator(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const username = inviteOperatorValues.username.trim();
    const expiresInHours = Number.parseInt(inviteOperatorValues.expiresInHours, 10);

    if (!selectedOperatorTenantId) {
      setOperatorNotice({
        kind: "error",
        message: "Selecione uma empresa antes de gerar o convite.",
      });
      return;
    }

    if (!username || !USERNAME_PATTERN.test(username)) {
      setOperatorNotice({
        kind: "error",
        message: "Use um usuário válido antes de gerar o convite.",
      });
      return;
    }

    if (!Number.isFinite(expiresInHours) || expiresInHours < 1) {
      setOperatorNotice({
        kind: "error",
        message: "Informe a validade do convite em horas.",
      });
      return;
    }

    setIsInvitingOperator(true);
    setOperatorNotice(null);
    setIssuedInvitation(null);

    try {
      const invitation = await createOperatorInvitation({
        tenantId: selectedOperatorTenantId,
        username,
        role: inviteOperatorValues.role,
        expiresInHours,
      });

      setInviteOperatorValues(buildInviteFormState());
      setIssuedInvitation(invitation);
      setOperatorNotice({
        kind: "success",
        message: `Convite gerado para ${invitation.username}. O token aparece abaixo somente nesta tela.`,
      });
    } catch (error) {
      setOperatorNotice({
        kind: "error",
        message: formatApiErrorMessage(error, "Não foi possível gerar o convite."),
      });
    } finally {
      setIsInvitingOperator(false);
    }
  }

  async function handleResetPassword(
    event: FormEvent<HTMLFormElement>,
    operator: OperatorResponse,
  ) {
    event.preventDefault();

    if (!resetPasswordValues.password.trim()) {
      setOperatorNotice({
        kind: "error",
        message: "Informe a nova senha provisória antes de concluir o reset.",
      });
      return;
    }

    setPendingOperatorAction(`reset:${operator.operator_id}`);
    setOperatorNotice(null);

    try {
      const updatedOperator = await resetOperatorAccountPassword(operator.operator_id, {
        tenantId: operator.tenant_id,
        newPassword: resetPasswordValues.password,
        requirePasswordChange: resetPasswordValues.requirePasswordChange,
      });

      setResetTargetOperatorId(null);
      setResetPasswordValues(INITIAL_RESET_PASSWORD_FORM_STATE);
      setOperatorNotice({
        kind: "success",
        message: updatedOperator.must_change_password
          ? `Senha provisória definida para ${updatedOperator.username}. As sessões ativas foram encerradas.`
          : `Senha atualizada para ${updatedOperator.username}. As sessões ativas foram encerradas.`,
      });
      setOperatorRefreshToken((currentValue) => currentValue + 1);
    } catch (error) {
      setOperatorNotice({
        kind: "error",
        message: formatApiErrorMessage(error, "Não foi possível resetar a senha do usuário."),
      });
    } finally {
      setPendingOperatorAction(null);
    }
  }

  async function handleDisableOperator(operator: OperatorResponse) {
    setPendingOperatorAction(`disable:${operator.operator_id}`);
    setOperatorNotice(null);

    try {
      const updatedOperator = await disableOperatorAccount(
        operator.operator_id,
        operator.tenant_id,
      );

      setOperatorNotice({
        kind: "success",
        message: `Usuário ${updatedOperator.username} desabilitado. As sessões ativas foram encerradas.`,
      });
      setOperatorRefreshToken((currentValue) => currentValue + 1);
    } catch (error) {
      setOperatorNotice({
        kind: "error",
        message: formatApiErrorMessage(error, "Não foi possível desabilitar o usuário."),
      });
    } finally {
      setPendingOperatorAction(null);
    }
  }

  async function handleCreateTenant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const tenantId = createTenantValues.tenantId.trim();
    const displayName = createTenantValues.displayName.trim();

    if (!tenantId || !TENANT_ID_PATTERN.test(tenantId)) {
      setTenantNotice({
        kind: "error",
        message: "Use um código de empresa em minúsculas com letras, números, ponto, hífen ou underscore.",
      });
      return;
    }

    if (!displayName) {
      setTenantNotice({
        kind: "error",
        message: "Informe o nome operacional da empresa.",
      });
      return;
    }

    setIsCreatingTenant(true);
    setTenantNotice(null);

    try {
      const tenant = await createAdminTenant({
        tenantId,
        displayName,
        aliases: parseAliases(createTenantValues.aliases),
      });

      setCreateTenantValues({
        tenantId: "",
        displayName: "",
        aliases: "",
      });
      setTenantNotice({
        kind: "success",
        message: `Empresa ${tenant.display_name} criada com o perfil padrão de validação.`,
      });
      setTenantRefreshToken((currentValue) => currentValue + 1);
    } catch (error) {
      setTenantNotice({
        kind: "error",
        message: formatApiErrorMessage(error, "Não foi possível criar a empresa."),
      });
    } finally {
      setIsCreatingTenant(false);
    }
  }

  async function handleSaveTenant(tenant: TenantAdminResponse) {
    const draft = tenantDrafts[tenant.tenant_id];
    if (!draft) {
      return;
    }

    setPendingTenantAction(`save:${tenant.tenant_id}`);
    setTenantNotice(null);

    try {
      const updatedTenant = await updateAdminTenant(tenant.tenant_id, {
        displayName: draft.displayName.trim(),
        aliases: parseAliases(draft.aliases),
      });

      setTenantNotice({
        kind: "success",
        message: `Dados da empresa ${updatedTenant.display_name} atualizados.`,
      });
      setTenantRefreshToken((currentValue) => currentValue + 1);
    } catch (error) {
      setTenantNotice({
        kind: "error",
        message: formatApiErrorMessage(error, "Não foi possível atualizar a empresa."),
      });
    } finally {
      setPendingTenantAction(null);
    }
  }

  async function handleToggleTenant(tenant: TenantAdminResponse) {
    const actionKey = `${tenant.disabled ? "reactivate" : "disable"}:${tenant.tenant_id}`;
    setPendingTenantAction(actionKey);
    setTenantNotice(null);

    try {
      const updatedTenant = tenant.disabled
        ? await reactivateAdminTenant(tenant.tenant_id)
        : await disableAdminTenant(tenant.tenant_id);

      setTenantNotice({
        kind: "success",
        message: updatedTenant.disabled
          ? `Empresa ${updatedTenant.display_name} desabilitada. Novos logins e operações ficaram bloqueados.`
          : `Empresa ${updatedTenant.display_name} reativada para uso administrativo e operacional.`,
      });
      setTenantRefreshToken((currentValue) => currentValue + 1);
      if (!updatedTenant.disabled) {
        setSelectedOperatorTenantId(updatedTenant.tenant_id);
      }
    } catch (error) {
      setTenantNotice({
        kind: "error",
        message: formatApiErrorMessage(
          error,
          tenant.disabled
            ? "Não foi possível reativar a empresa."
            : "Não foi possível desabilitar a empresa.",
        ),
      });
    } finally {
      setPendingTenantAction(null);
    }
  }

  async function handleSaveProfileDraft() {
    const tenantId = selectedProfileTenantId || sessionTenantId;
    let parsedProfile: TenantValidationProfileData;

    try {
      parsedProfile = parseProfileJson(profileJson);
    } catch {
      setProfileNotice({
        kind: "error",
        message: "O JSON do perfil está inválido. Corrija a sintaxe antes de salvar.",
      });
      return;
    }

    setPendingProfileAction("save-draft");
    setProfileNotice(null);

    try {
      const payload = await saveTenantValidationProfileDraft(tenantId, parsedProfile);
      setProfileState(payload);
      setProfileJson(formatProfileJson(payload.draft?.profile || payload.current_profile));
      setProfileNotice({
        kind: "success",
        message: "Rascunho salvo. A validação em produção continua usando a versão publicada.",
      });
    } catch (error) {
      setProfileNotice({
        kind: "error",
        message: formatApiErrorMessage(error, "Não foi possível salvar o rascunho do perfil."),
      });
    } finally {
      setPendingProfileAction(null);
    }
  }

  async function handlePublishProfileDraft() {
    const tenantId = selectedProfileTenantId || sessionTenantId;
    setPendingProfileAction("publish");
    setProfileNotice(null);

    try {
      const payload = await publishTenantValidationProfileDraft(tenantId);
      setProfileState(payload);
      setProfileJson(formatProfileJson(payload.current_profile));
      setProfileNotice({
        kind: "success",
        message: `Perfil publicado na versão ${payload.published_version?.version_number ?? ""}. Novos lotes usarão essa configuração.`,
      });
    } catch (error) {
      setProfileNotice({
        kind: "error",
        message: formatApiErrorMessage(error, "Não foi possível publicar o perfil."),
      });
    } finally {
      setPendingProfileAction(null);
    }
  }

  async function handleRollbackProfile(versionId: string) {
    const tenantId = selectedProfileTenantId || sessionTenantId;
    setPendingProfileAction(`rollback:${versionId}`);
    setProfileNotice(null);

    try {
      const payload = await rollbackTenantValidationProfile(tenantId, versionId);
      setProfileState(payload);
      setProfileJson(formatProfileJson(payload.current_profile));
      setProfileNotice({
        kind: "success",
        message: `Rollback publicado como versão ${payload.published_version?.version_number ?? ""}.`,
      });
    } catch (error) {
      setProfileNotice({
        kind: "error",
        message: formatApiErrorMessage(error, "Não foi possível reverter o perfil."),
      });
    } finally {
      setPendingProfileAction(null);
    }
  }

  const roleOptions = getAllowedRoleOptions(role);

  return (
    <section className="panel admin-console-card" aria-label="Console administrativo">
      <div className="admin-console-head">
        <div>
          <div className="panel-kicker">Administração</div>
          <h2 className="panel-title">Console administrativo</h2>
          <p className="panel-copy">
            Use esta área apenas quando precisar gerenciar empresas ou usuários. A conferência
            patrimonial continua logo abaixo.
          </p>
        </div>
        <div className="admin-console-actions">
          <span className="status-chip info">{getRoleLabel(role)}</span>
          <button className="action-button" type="button" onClick={onClose}>
            Fechar administração
          </button>
        </div>
      </div>

      <div className="admin-section-switcher" role="tablist" aria-label="Seções administrativas">
        <button
          className={`action-button${activeSection === "operators" ? " primary" : ""}`}
          type="button"
          role="tab"
          aria-selected={activeSection === "operators"}
          onClick={() => setActiveSection("operators")}
        >
          Usuários
        </button>
        {isPlatformAdmin(role) ? (
          <button
            className={`action-button${activeSection === "tenants" ? " primary" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeSection === "tenants"}
            onClick={() => setActiveSection("tenants")}
          >
            Empresas
          </button>
        ) : null}
        <button
          className={`action-button${activeSection === "profiles" ? " primary" : ""}`}
          type="button"
          role="tab"
          aria-selected={activeSection === "profiles"}
          onClick={() => setActiveSection("profiles")}
        >
          Perfis
        </button>
      </div>

      {activeSection === "operators" ? (
        <div className="admin-console-body">
          <div className="admin-grid">
            <section className="admin-subcard">
              <div className="admin-subhead">
                <strong>Empresa em foco</strong>
                <p>
                  {isPlatformAdmin(role)
                    ? "Escolha a empresa onde você deseja criar ou ajustar usuários."
                    : "Como administrador da empresa, você só enxerga o seu próprio quadro de usuários."}
                </p>
              </div>

              {isPlatformAdmin(role) ? (
                <div className="field">
                  <label htmlFor="admin-operator-tenant">Empresa</label>
                  <select
                    id="admin-operator-tenant"
                    value={selectedOperatorTenantId}
                    disabled={isTenantsLoading || !operatorTenantOptions.length}
                    onChange={(event) => setSelectedOperatorTenantId(event.target.value)}
                  >
                    {operatorTenantOptions.map((tenant) => (
                      <option key={tenant.tenant_id} value={tenant.tenant_id}>
                        {tenant.display_name} ({tenant.tenant_id})
                      </option>
                    ))}
                  </select>
                  {selectedOperatorTenant ? (
                    <small>
                      Empresa ativa: {selectedOperatorTenant.display_name}. Usuários e convites
                      serão criados nesse contexto.
                    </small>
                  ) : null}
                </div>
              ) : (
                <div className="tenant-context">
                  <strong>{sessionTenantId}</strong>
                  <span>{getRoleLabel(role)}</span>
                </div>
              )}

              {tenantLoadError ? <p className="inline-error">{tenantLoadError}</p> : null}
            </section>

            <section className="admin-subcard">
              <div className="admin-subhead">
                <strong>Criar usuário</strong>
                <p>Defina um acesso direto com senha inicial e papel compatível com o seu escopo.</p>
              </div>

              <form className="form-grid" onSubmit={handleCreateOperator}>
                <div className="field">
                  <label htmlFor="admin-create-username">Usuário do novo acesso</label>
                  <input
                    id="admin-create-username"
                    type="text"
                    value={createOperatorValues.username}
                    onChange={handleCreateOperatorFieldChange("username")}
                  />
                </div>

                <div className="field">
                  <label htmlFor="admin-create-password">Senha inicial</label>
                  <input
                    id="admin-create-password"
                    type="password"
                    value={createOperatorValues.password}
                    onChange={handleCreateOperatorFieldChange("password")}
                  />
                  <small>Use uma senha forte. O backend valida a política mínima.</small>
                </div>

                <div className="field">
                  <label htmlFor="admin-create-role">Papel</label>
                  <select
                    id="admin-create-role"
                    value={createOperatorValues.role}
                    onChange={handleCreateOperatorFieldChange("role")}
                  >
                    {roleOptions.map((option) => (
                      <option key={option} value={option}>
                        {getRoleLabel(option)}
                      </option>
                    ))}
                  </select>
                </div>

                <label className="admin-checkbox">
                  <input
                    type="checkbox"
                    checked={createOperatorValues.requirePasswordChange}
                    onChange={handleCreateOperatorFieldChange("requirePasswordChange")}
                  />
                  <span>Obrigar troca de senha no primeiro login.</span>
                </label>

                <button className="cta" type="submit" disabled={isCreatingOperator}>
                  {isCreatingOperator ? "Criando usuário..." : "Criar usuário"}
                </button>
              </form>
            </section>

            <section className="admin-subcard">
              <div className="admin-subhead">
                <strong>Convidar usuário</strong>
                <p>Gere um convite single-use quando preferir que a senha seja criada pelo próprio usuário.</p>
              </div>

              <form className="form-grid" onSubmit={handleInviteOperator}>
                <div className="field">
                  <label htmlFor="admin-invite-username">Usuário do convite</label>
                  <input
                    id="admin-invite-username"
                    type="text"
                    value={inviteOperatorValues.username}
                    onChange={handleInviteFieldChange("username")}
                  />
                </div>

                <div className="field">
                  <label htmlFor="admin-invite-role">Papel</label>
                  <select
                    id="admin-invite-role"
                    value={inviteOperatorValues.role}
                    onChange={handleInviteFieldChange("role")}
                  >
                    {roleOptions.map((option) => (
                      <option key={option} value={option}>
                        {getRoleLabel(option)}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label htmlFor="admin-invite-hours">Validade do convite</label>
                  <input
                    id="admin-invite-hours"
                    type="number"
                    min={1}
                    max={720}
                    value={inviteOperatorValues.expiresInHours}
                    onChange={handleInviteFieldChange("expiresInHours")}
                  />
                </div>

                <button className="action-link" type="submit" disabled={isInvitingOperator}>
                  {isInvitingOperator ? "Gerando convite..." : "Gerar convite"}
                </button>
              </form>
            </section>
          </div>

          {operatorNotice ? (
            <div className={`admin-notice ${operatorNotice.kind}`} role="status">
              <strong>{operatorNotice.kind === "success" ? "Ação concluída" : "Ação não concluída"}</strong>
              <p>{operatorNotice.message}</p>
            </div>
          ) : null}

          {issuedInvitation ? (
            <section className="admin-subcard admin-token-card">
              <div className="admin-subhead">
                <strong>Convite pronto para uso</strong>
                <p>
                  Usuário {issuedInvitation.username} • expira em{" "}
                  {new Date(issuedInvitation.expires_at).toLocaleString("pt-BR")}
                </p>
              </div>
              <div className="field">
                <label htmlFor="admin-issued-invite-token">Token do convite</label>
                <input
                  id="admin-issued-invite-token"
                  type="text"
                  readOnly
                  value={issuedInvitation.invite_token}
                />
              </div>
            </section>
          ) : null}

          <section className="admin-subcard">
            <div className="admin-subhead">
              <strong>Usuários cadastrados</strong>
              <p>
                Revise contas ativas, redefina senhas provisórias e desabilite acessos que não
                devem mais operar.
              </p>
            </div>

            {operatorLoadError ? <p className="inline-error">{operatorLoadError}</p> : null}
            {isOperatorsLoading ? (
              <p className="job-empty">Carregando usuários...</p>
            ) : operators.length ? (
              <div className="admin-operator-list">
                {operators.map((operator) => {
                  const actionInFlight = pendingOperatorAction?.endsWith(operator.operator_id);
                  const isResetOpen = resetTargetOperatorId === operator.operator_id;

                  return (
                    <article className="admin-operator-card" key={operator.operator_id}>
                      <div className="admin-operator-head">
                        <div>
                          <strong>{operator.username}</strong>
                          <p>
                            {getRoleLabel(operator.role)} • {getOperatorStatusSummary(operator)}
                          </p>
                        </div>
                        <div className="admin-chip-row">
                          {operator.is_seed ? (
                            <span className="status-chip info">Seed</span>
                          ) : null}
                          {operator.disabled ? (
                            <span className="status-chip warning">Desabilitado</span>
                          ) : null}
                          {operator.must_change_password ? (
                            <span className="status-chip warning">Senha provisória</span>
                          ) : (
                            <span className="status-chip success">Ativo</span>
                          )}
                        </div>
                      </div>

                      <p className="admin-operator-meta">
                        ID técnico: {operator.operator_id} • Empresa {operator.tenant_id}
                      </p>

                      <div className="admin-row-actions">
                        {!operator.disabled ? (
                          <>
                            <button
                              className="action-button"
                              type="button"
                              onClick={() => {
                                setResetTargetOperatorId(operator.operator_id);
                                setResetPasswordValues(INITIAL_RESET_PASSWORD_FORM_STATE);
                                setOperatorNotice(null);
                              }}
                              disabled={Boolean(actionInFlight)}
                            >
                              Preparar nova senha
                            </button>
                            <button
                              className="action-button"
                              type="button"
                              onClick={() => void handleDisableOperator(operator)}
                              disabled={Boolean(actionInFlight)}
                            >
                              {pendingOperatorAction === `disable:${operator.operator_id}`
                                ? "Desabilitando..."
                                : "Desabilitar"}
                            </button>
                          </>
                        ) : (
                          <p className="job-empty">
                            Conta desabilitada. A reativação ainda não faz parte deste painel.
                          </p>
                        )}
                      </div>

                      {isResetOpen ? (
                        <form
                          className="form-grid admin-inline-form"
                          onSubmit={(event) => void handleResetPassword(event, operator)}
                        >
                          <div className="field">
                            <label htmlFor={`reset-password-${operator.operator_id}`}>
                              Nova senha
                            </label>
                            <input
                              id={`reset-password-${operator.operator_id}`}
                              type="password"
                              value={resetPasswordValues.password}
                              onChange={handleResetPasswordFieldChange("password")}
                            />
                          </div>

                          <label className="admin-checkbox">
                            <input
                              type="checkbox"
                              checked={resetPasswordValues.requirePasswordChange}
                              onChange={handleResetPasswordFieldChange("requirePasswordChange")}
                            />
                            <span>Obrigar troca imediata de senha no próximo login.</span>
                          </label>

                          <div className="admin-row-actions">
                            <button
                              className="cta"
                              type="submit"
                              disabled={pendingOperatorAction === `reset:${operator.operator_id}`}
                            >
                              {pendingOperatorAction === `reset:${operator.operator_id}`
                                ? "Salvando..."
                                : "Salvar nova senha"}
                            </button>
                            <button
                              className="action-button"
                              type="button"
                              onClick={() => {
                                setResetTargetOperatorId(null);
                                setResetPasswordValues(INITIAL_RESET_PASSWORD_FORM_STATE);
                              }}
                            >
                              Cancelar
                            </button>
                          </div>
                        </form>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="audit-empty-card">
                <strong>Nenhum usuário adicional cadastrado</strong>
                <p>Crie um usuário direto ou gere um convite para começar a distribuir acessos.</p>
              </div>
            )}
          </section>
        </div>
      ) : activeSection === "tenants" ? (
        <div className="admin-console-body">
          <div className="admin-grid">
            <section className="admin-subcard">
              <div className="admin-subhead">
                <strong>Nova empresa</strong>
                <p>
                  Crie o tenant com o perfil padrão e depois ajuste regras mais específicas no
                  backend quando necessário.
                </p>
              </div>

              <form className="form-grid" onSubmit={handleCreateTenant}>
                <div className="field">
                  <label htmlFor="admin-create-tenant-id">Código da empresa</label>
                  <input
                    id="admin-create-tenant-id"
                    type="text"
                    value={createTenantValues.tenantId}
                    onChange={handleCreateTenantFieldChange("tenantId")}
                  />
                </div>

                <div className="field">
                  <label htmlFor="admin-create-tenant-name">Nome operacional</label>
                  <input
                    id="admin-create-tenant-name"
                    type="text"
                    value={createTenantValues.displayName}
                    onChange={handleCreateTenantFieldChange("displayName")}
                  />
                </div>

                <div className="field">
                  <label htmlFor="admin-create-tenant-aliases">Aliases</label>
                  <input
                    id="admin-create-tenant-aliases"
                    type="text"
                    value={createTenantValues.aliases}
                    onChange={handleCreateTenantFieldChange("aliases")}
                    placeholder="alias-1, alias-2"
                  />
                  <small>Separe aliases por vírgula. Use apenas quando houver compatibilidade legada.</small>
                </div>

                <button className="cta" type="submit" disabled={isCreatingTenant}>
                  {isCreatingTenant ? "Criando empresa..." : "Criar empresa"}
                </button>
              </form>
            </section>
          </div>

          {tenantNotice ? (
            <div className={`admin-notice ${tenantNotice.kind}`} role="status">
              <strong>{tenantNotice.kind === "success" ? "Ação concluída" : "Ação não concluída"}</strong>
              <p>{tenantNotice.message}</p>
            </div>
          ) : null}

          {tenantLoadError ? <p className="inline-error">{tenantLoadError}</p> : null}
          {isTenantsLoading ? (
            <p className="job-empty">Carregando empresas...</p>
          ) : (
            <div className="admin-tenant-list">
              {tenants.map((tenant) => {
                const draft = tenantDrafts[tenant.tenant_id] || {
                  displayName: tenant.display_name,
                  aliases: formatAliases(tenant.aliases),
                };
                const isSaveDisabled =
                  pendingTenantAction === `save:${tenant.tenant_id}` ||
                  (draft.displayName.trim() === tenant.display_name &&
                    parseAliases(draft.aliases).join("|") === tenant.aliases.join("|"));
                const toggleActionKey = `${tenant.disabled ? "reactivate" : "disable"}:${tenant.tenant_id}`;

                return (
                  <article className="admin-tenant-card" key={tenant.tenant_id}>
                    <div className="admin-tenant-head">
                      <div>
                        <strong>{tenant.display_name}</strong>
                        <p>
                          {tenant.tenant_id} • {getTenantSourceLabel(tenant.source)}
                        </p>
                      </div>
                      <div className="admin-chip-row">
                        {tenant.is_default ? (
                          <span className="status-chip info">Padrão</span>
                        ) : null}
                        {tenant.disabled ? (
                          <span className="status-chip warning">Desabilitada</span>
                        ) : (
                          <span className="status-chip success">Ativa</span>
                        )}
                      </div>
                    </div>

                    <div className="admin-tenant-form">
                      <div className="field">
                        <label htmlFor={`tenant-name-${tenant.tenant_id}`}>Nome operacional</label>
                        <input
                          id={`tenant-name-${tenant.tenant_id}`}
                          type="text"
                          value={draft.displayName}
                          onChange={handleTenantDraftChange(tenant.tenant_id, "displayName")}
                        />
                      </div>

                      <div className="field">
                        <label htmlFor={`tenant-aliases-${tenant.tenant_id}`}>Aliases</label>
                        <input
                          id={`tenant-aliases-${tenant.tenant_id}`}
                          type="text"
                          value={draft.aliases}
                          onChange={handleTenantDraftChange(tenant.tenant_id, "aliases")}
                          placeholder="alias-1, alias-2"
                        />
                      </div>
                    </div>

                    <div className="admin-row-actions">
                      <button
                        className="action-button"
                        type="button"
                        onClick={() => void handleSaveTenant(tenant)}
                        disabled={isSaveDisabled}
                      >
                        {pendingTenantAction === `save:${tenant.tenant_id}`
                          ? "Salvando..."
                          : "Salvar dados"}
                      </button>

                      {!tenant.is_default ? (
                        <button
                          className="action-button"
                          type="button"
                          onClick={() => void handleToggleTenant(tenant)}
                          disabled={pendingTenantAction === toggleActionKey}
                        >
                          {pendingTenantAction === toggleActionKey
                            ? tenant.disabled
                              ? "Reativando..."
                              : "Desabilitando..."
                            : tenant.disabled
                              ? "Reativar"
                              : "Desabilitar"}
                        </button>
                      ) : null}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        <div className="admin-console-body">
          <section className="admin-subcard">
            <div className="admin-subhead">
              <strong>Perfil de validação</strong>
              <p>
                Edite regras, thresholds, categorias, normalização e referência de prompt em
                rascunho. Apenas a publicação muda o perfil usado por novos lotes.
              </p>
            </div>

            <div className="admin-tenant-form">
              {isPlatformAdmin(role) ? (
                <div className="field">
                  <label htmlFor="admin-profile-tenant">Empresa</label>
                  <select
                    id="admin-profile-tenant"
                    value={selectedProfileTenantId}
                    disabled={isTenantsLoading || !profileTenantOptions.length}
                    onChange={(event) => setSelectedProfileTenantId(event.target.value)}
                  >
                    {profileTenantOptions.map((tenant) => (
                      <option key={tenant.tenant_id} value={tenant.tenant_id}>
                        {tenant.display_name} ({tenant.tenant_id})
                      </option>
                    ))}
                  </select>
                  <small>Tenants desabilitados continuam visíveis para histórico e rollback.</small>
                </div>
              ) : (
                <div className="tenant-context">
                  <strong>{sessionTenantId}</strong>
                  <span>Perfil da sua empresa</span>
                </div>
              )}

              {profileState ? (
                <div className="admin-chip-row">
                  <span className="status-chip info">
                    {getProfileSourceLabel(profileState.source)}
                  </span>
                  {profileState.published_version ? (
                    <span className="status-chip success">
                      v{profileState.published_version.version_number}
                    </span>
                  ) : null}
                  {profileState.draft ? (
                    <span className="status-chip warning">Rascunho não publicado</span>
                  ) : null}
                </div>
              ) : null}
            </div>
          </section>

          {profileNotice ? (
            <div className={`admin-notice ${profileNotice.kind}`} role="status">
              <strong>{profileNotice.kind === "success" ? "Ação concluída" : "Ação não concluída"}</strong>
              <p>{profileNotice.message}</p>
            </div>
          ) : null}

          {profileLoadError ? <p className="inline-error">{profileLoadError}</p> : null}
          {isProfileLoading ? (
            <p className="job-empty">Carregando perfil de validação...</p>
          ) : profileState ? (
            <>
              <section className="admin-subcard">
                <div className="admin-subhead">
                  <strong>Editor JSON do perfil</strong>
                  <p>
                    O backend valida schema e consistência no momento da publicação. Mantenha
                    apenas campos de perfil; credenciais e usuários não fazem parte deste payload.
                  </p>
                </div>

                <div className="field">
                  <label htmlFor="admin-profile-json">Configuração do perfil</label>
                  <textarea
                    id="admin-profile-json"
                    rows={18}
                    value={profileJson}
                    onChange={(event) => {
                      setProfileJson(event.target.value);
                      setProfileNotice(null);
                    }}
                  />
                </div>

                <div className="admin-row-actions">
                  <button
                    className="action-button"
                    type="button"
                    onClick={() => void handleSaveProfileDraft()}
                    disabled={pendingProfileAction === "save-draft"}
                  >
                    {pendingProfileAction === "save-draft"
                      ? "Salvando rascunho..."
                      : "Salvar rascunho"}
                  </button>
                  <button
                    className="cta"
                    type="button"
                    onClick={() => void handlePublishProfileDraft()}
                    disabled={!profileState.draft || pendingProfileAction === "publish"}
                  >
                    {pendingProfileAction === "publish" ? "Publicando..." : "Publicar perfil"}
                  </button>
                </div>
              </section>

              <section className="admin-subcard">
                <div className="admin-subhead">
                  <strong>Histórico publicado</strong>
                  <p>
                    Rollbacks criam uma nova versão publicada, preservando a trilha de versões
                    anteriores para auditoria.
                  </p>
                </div>

                {profileState.versions.length ? (
                  <div className="admin-tenant-list">
                    {profileState.versions.map((version) => (
                      <article className="admin-tenant-card" key={version.version_id}>
                        <div className="admin-tenant-head">
                          <div>
                            <strong>Versão {version.version_number}</strong>
                            <p>
                              {new Date(version.published_at).toLocaleString("pt-BR")} •{" "}
                              {version.published_by_username || "autor não informado"}
                            </p>
                          </div>
                          <div className="admin-chip-row">
                            <span className="status-chip info">
                              {version.source === "rollback" ? "Rollback" : "Publicação"}
                            </span>
                          </div>
                        </div>

                        <div className="admin-row-actions">
                          <button
                            className="action-button"
                            type="button"
                            onClick={() => void handleRollbackProfile(version.version_id)}
                            disabled={
                              pendingProfileAction === `rollback:${version.version_id}` ||
                              version.version_id === profileState.published_version?.version_id
                            }
                          >
                            {pendingProfileAction === `rollback:${version.version_id}`
                              ? "Revertendo..."
                              : "Reverter para esta versão"}
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="audit-empty-card">
                    <strong>Nenhuma versão publicada pela aplicação</strong>
                    <p>O tenant ainda usa o perfil bootstrap carregado de arquivo.</p>
                  </div>
                )}
              </section>
            </>
          ) : null}
        </div>
      )}
    </section>
  );
}
