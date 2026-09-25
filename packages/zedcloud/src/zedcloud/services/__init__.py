"""Service namespaces attached to the Zedcloud clients.

Generated classes are re-exported here; namespaces that need hand-written
conveniences subclass their generated base in a sibling module.
"""

from zedcloud._generated.services.app_profiles import AppProfilesService, AsyncAppProfilesService
from zedcloud._generated.services.apps import AppsService, AsyncAppsService
from zedcloud._generated.services.diag import AsyncDiagService, DiagService
from zedcloud._generated.services.iam import AsyncIamService, IamService
from zedcloud._generated.services.jobs import AsyncJobsService, JobsService
from zedcloud._generated.services.k8s import AsyncK8sService, K8sService
from zedcloud._generated.services.networks import AsyncNetworksService, NetworksService
from zedcloud._generated.services.node_clusters import AsyncNodeClustersService, NodeClustersService
from zedcloud._generated.services.nodes import AsyncNodesService, NodesService
from zedcloud._generated.services.orchestration import (
    AsyncOrchestrationService,
    OrchestrationService,
)
from zedcloud._generated.services.storage import AsyncStorageService, StorageService

__all__ = [
    "AppProfilesService",
    "AppsService",
    "AsyncAppProfilesService",
    "AsyncAppsService",
    "AsyncDiagService",
    "AsyncIamService",
    "AsyncJobsService",
    "AsyncK8sService",
    "AsyncNetworksService",
    "AsyncNodeClustersService",
    "AsyncNodesService",
    "AsyncOrchestrationService",
    "AsyncStorageService",
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
