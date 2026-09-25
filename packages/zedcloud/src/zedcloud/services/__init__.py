"""Service namespaces attached to :class:`~zedcloud.client.ZedcloudClient`."""

from zedcloud._generated.services.app_profiles import AppProfilesService
from zedcloud._generated.services.apps import AppsService
from zedcloud._generated.services.diag import DiagService
from zedcloud._generated.services.iam import IamService
from zedcloud._generated.services.jobs import JobsService
from zedcloud._generated.services.k8s import K8sService
from zedcloud._generated.services.networks import NetworksService
from zedcloud._generated.services.node_clusters import NodeClustersService
from zedcloud._generated.services.nodes import NodesService
from zedcloud._generated.services.orchestration import OrchestrationService
from zedcloud._generated.services.storage import StorageService

__all__ = [
    "AppProfilesService",
    "AppsService",
    "DiagService",
    "IamService",
    "JobsService",
    "K8sService",
    "NetworksService",
    "NodeClustersService",
    "NodesService",
    "OrchestrationService",
    "StorageService",
]
