#!/usr/bin/env python3

from BlazeposeRenderer import BlazeposeRenderer
import argparse
import numpy as np
import matplotlib.pyplot as plt
from collections import deque
import render 
from djitellopy import tello
from Socket import Socket
from drone_movement import *

parser = argparse.ArgumentParser()
parser.add_argument('-e', '--edge', action="store_true",
                    help="Use Edge mode (postprocessing runs on the device)")
parser_tracker = parser.add_argument_group("Tracker arguments")                 
parser_tracker.add_argument('-i', '--input', type=str, default="rgb", 
                    help="'rgb' or 'rgb_laconic' or path to video/image file to use as input (default=%(default)s)")
parser_tracker.add_argument("--pd_m", type=str,
                    help="Path to an .blob file for pose detection model")
parser_tracker.add_argument("--lm_m", type=str,
                    help="Landmark model ('full' or 'lite' or 'heavy') or path to an .blob file")
parser_tracker.add_argument('-xyz', '--xyz', action="store_true", 
                    help="Get (x,y,z) coords of reference body keypoint in camera coord system (only for compatible devices)")
parser_tracker.add_argument('-c', '--crop', action="store_true", 
                    help="Center crop frames to a square shape before feeding pose detection model")
parser_tracker.add_argument('--no_smoothing', action="store_true", 
                    help="Disable smoothing filter")
parser_tracker.add_argument('-f', '--internal_fps', type=int, 
                    help="Fps of internal color camera. Too high value lower NN fps (default= depends on the model)")                    
parser_tracker.add_argument('--internal_frame_height', type=int, default=640,                                                                                    
                    help="Internal color camera frame height in pixels (default=%(default)i)")                    
parser_tracker.add_argument('-s', '--stats', action="store_true", 
                    help="Print some statistics at exit")
parser_tracker.add_argument('-t', '--trace', action="store_true", 
                    help="Print some debug messages")
parser_tracker.add_argument('--force_detection', action="store_true", 
                    help="Force person detection on every frame (never use landmarks from previous frame to determine ROI)")

parser_renderer = parser.add_argument_group("Renderer arguments")
parser_renderer.add_argument('-3', '--show_3d', choices=[None, "image", "world", "mixed"], default=None,
                    help="Display skeleton in 3d in a separate window. See README for description.")
parser_renderer.add_argument("-o","--output",
                    help="Path to output video file")
 

args = parser.parse_args()
args.edge = True

if args.edge:
    from BlazeposeDepthaiEdge import BlazeposeDepthai
else:
    from BlazeposeDepthai import BlazeposeDepthai

tracker = BlazeposeDepthai(input_src=args.input, 
            pd_model=args.pd_m,
            lm_model=args.lm_m,
            smoothing=not args.no_smoothing,   
            xyz=True, #args.xyz,            
            crop=args.crop,
            internal_fps=args.internal_fps,
            internal_frame_height=args.internal_frame_height,
            force_detection=args.force_detection,
            stats=True,
            trace=args.trace)   

renderer = BlazeposeRenderer(
                tracker, 
                # show_3d=args.show_3d, 
                show_3d="drone", 
                output=args.output)


def calc_pose_vector(body):
    '''
        trajectory = []

        while True:
            get frame, body
            
            calculate pose of:
                Righ wrist
                Left wrist
                Right ankle
                Left ankle
                left eye
                right eye
                left torso
                right torso
                centroid
            in current frame
            
            
            if previous frame is None:
                previous frame
                initialize queue points
                continue
            store in queue

            traverse queue:
                calculate distance for each element in the pose_vector
            
            previous frame = current frame
            queue pop
    '''
    if not hasattr(body, 'xyz'):
        return None
    # if body.xyz_ref:
    # Righ wrist
    right_wrist = body.landmarks_world[16]
    # Left wrist
    left_wrist = body.landmarks_world[15]
    # Right ankle
    right_ankle = body.landmarks_world[28]
    # Left ankle
    left_ankle = body.landmarks_world[27]
    # right eye
    right_eye = body.landmarks_world[5]
    # left eye
    left_eye = body.landmarks_world[2]
    # right hip
    right_hip = body.landmarks_world[24]
    # left hip
    left_hip = body.landmarks_world[23]
    #centroid (just considering hip joints for this)
    centroid = (left_hip + right_hip) /2
    
    translation = body.xyz / 1000
    translation[1] = -translation[1]
    
    # if body.xyz_ref == "mid_shoulders":
    #     mid_hips_to_mid_shoulders = body.landmarks_world[11] + body.landmarks_world[12] /2 
    #     translation -= mid_hips_to_mid_shoulders   

    pose_vec = np.array([
        right_wrist, left_wrist,
        right_ankle, left_ankle,
        right_eye, left_eye,
        right_hip, left_hip,
        centroid
    ])

    pose_vec = pose_vec + translation
    
    # else:
    #     pose_vec = np.zeros((NUM_LANDMARKS, 3))

    # pose_vec += body.xyz
    return pose_vec

def distance(pose1, pose2):
    return pose2-pose1

def randomize_init_drone_pos(body_landmarks):
    '''
    take pose of human eye centers
    add a constant value
    add a random noise to it
    '''
    human_head_center = body_landmarks[5]+body_landmarks[6]/2
    # const_distance = np.array([[5, 5, -5],
    #                            [5, 5, -5],
    #                            [7, 4, -5],
    #                            [7, 4, -5]])
    # noise = np.random.rand(4,3)*2
    # return human_head_center + const_distance + noise

    const_distance = np.array([[0, 0, 0],
                               [5, 5, -5],
                               [7, 4, -5],
                               [7, 4, -5]])
    return const_distance

def project_motion_to_drone(pose):
    #calc weight
    distance = np.linalg.norm(pose, axis=1)
    weight = distance/np.sum(distance)
    # print('weight: '+ str(weight))
    # print('pose: '+ str(pose))
    
    major_pose_change_idx = np.argmax(weight)
    ##TODO send signal to drone
    ## send pose pos (of major_pose_change_idx) projected in drone frame
    
    new_pose = renderer.project_to_drone(pose[major_pose_change_idx])
    print("In project motion to drone: ", new_pose)
    return new_pose


NUM_LANDMARKS = 9
trajectory = np.zeros((NUM_LANDMARKS,3))
previous_frame = None

list_of_points = np.array([])
i=0
count = 0
while True:
    # Run blazepose on next frame
    frame, body = tracker.next_frame()
    if frame is None: break
    if body is None: continue

    # Draw 2d skeleton
    frame = renderer.draw(frame, body)
    key = renderer.waitKey(delay=1)

    current_pose = calc_pose_vector(body)

    if current_pose is None:
        print('Body Reference not found, skipping frame. Put shoulder or waist in frame.')
        continue

    # print(current_pose)
    if previous_frame is not None:
        del_t_distance = distance(previous_pose, current_pose)
        #update trajectory
        trajectory+=del_t_distance
    else:
        drone_pos = randomize_init_drone_pos(current_pose)
        renderer.spawn_drones(drone_pos)
    

    if i%10 and i!=0:
        new_positions = project_motion_to_drone(trajectory)
        print("new position: ", new_positions)
        list_of_points = np.append(list_of_points, new_positions[0])
        # reset trajectory
        trajectory = np.zeros((NUM_LANDMARKS,3))

    previous_frame = frame
    previous_pose = current_pose
    i+=1
    if (i == 10): 
        # render.draw_drones(list_of_points)
        break

# print(list_of_points)

list_of_points = list_of_points.reshape(-1,3)*10

speed = np.ones((list_of_points.shape[0], 1))*25
command_list = np.hstack([list_of_points, speed])

np.save('command_list.npy', command_list)

print('Starting projection')

# sock = Socket(client_ip = '169.254.222.143', \
#                   server_ip = '169.254.176.231', port = 4000)
            
drone = tello.Tello()
drone.connect()

sock = Socket(client_ip = '169.254.222.143', \
            server_ip = '169.254.176.231', port = 4000)
    


parallelize(command_list, drone, sock)
